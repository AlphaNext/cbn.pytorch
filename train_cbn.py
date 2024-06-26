import torch
import numpy as np
import random
import argparse
import os
import os.path as osp
import sys
import time
import json
from mmcv import Config

from dataset import build_data_loader
from models import build_model
from utils import AverageMeter

torch.manual_seed(123456)
torch.cuda.manual_seed(123456)
np.random.seed(123456)
random.seed(123456)


def train(train_loader, model, optimizer, epoch, start_iter, cfg):
    model.train()
    # meters
    batch_time = AverageMeter()
    data_time = AverageMeter()

    losses = AverageMeter()
    losses_text = AverageMeter()
    losses_kernels = AverageMeter()
    losses_emb = AverageMeter()
    losses_dist = AverageMeter()

    losses_augtext = AverageMeter()
    losses_augkernel = AverageMeter()
    
    ious_text = AverageMeter()
    ious_kernel = AverageMeter()
    accs_rec = AverageMeter()
    
    ious_augtext = AverageMeter()
    ious_augkernel = AverageMeter()

    # start time
    start = time.time()
    for iter, data in enumerate(train_loader):
        # skip previous iterations
        if iter < start_iter:
            print('Skipping iter: %d' % iter)
            sys.stdout.flush()
            continue

        # time cost of data loader
        data_time.update(time.time() - start)

        # adjust learning rate
        adjust_learning_rate(optimizer, train_loader, epoch, iter, cfg)

        # prepare input
        data.update(dict(cfg=cfg))

        # forward
        outputs = model(**data)

        # detection loss
        loss_text = torch.mean(outputs['loss_text'])
        losses_text.update(loss_text.item())

        loss_kernels = torch.mean(outputs['loss_kernels'])
        losses_kernels.update(loss_kernels.item())

        loss_dist = torch.mean(outputs['loss_dist'])
        losses_dist.update(loss_dist.item())
        
        loss_augtext = torch.mean(outputs['loss_augtext'])
        losses_augtext.update(loss_augtext.item())
        
        loss_augkernel = torch.mean(outputs['loss_augkernels'])
        losses_augkernel.update(loss_augkernel.item())
        
        if 'loss_emb' in outputs.keys():
            loss_emb = torch.mean(outputs['loss_emb'])
            losses_emb.update(loss_emb.item())
            loss = loss_text + loss_kernels + loss_dist + loss_augtext + loss_augkernel +  loss_emb
        else:
            loss = loss_text + loss_kernels + loss_dist + loss_augtext + loss_augkernel

        iou_text = torch.mean(outputs['iou_text'])
        ious_text.update(iou_text.item())
        iou_kernel = torch.mean(outputs['iou_kernel'])
        ious_kernel.update(iou_kernel.item())

        iou_augtext = torch.mean(outputs['iou_augtext'])
        ious_augtext.update(iou_augtext.item())
        
        iou_augkernel = torch.mean(outputs['iou_augkernel'])
        ious_augkernel.update(iou_augkernel.item())
        
        losses.update(loss.item())
        # backward
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        batch_time.update(time.time() - start)

        # update start time
        start = time.time()

        # print log
        if iter % 20 == 0:
            output_log = '({batch}/{size}) LR: {lr:.6f} | Batch: {bt:.3f}s | Total: {total:.0f}min | ' \
                         'ETA: {eta:.0f}min | Loss: {loss:.3f} | ' \
                         'Loss(text/kernel/augtext/augkernel): {loss_text:.3f}/{loss_kernel:.3f}/{loss_augtext:.3f}/{loss_augkernel:.3f} ' \
                         '| IoU(text/kernel/augtext/augkernel): {iou_text:.3f}/{iou_kernel:.3f}/{iou_augtext:.3f}/{iou_augkernel:.3f} | ' \
                         'Distmap: {loss_dist:.3f} | loss_emb: {loss_emb:.3f} | Acc rec: {acc_rec:.3f}'.format(
                batch=iter + 1,
                size=len(train_loader),
                lr=optimizer.param_groups[0]['lr'],
                bt=batch_time.avg,
                total=batch_time.avg * iter / 60.0,
                eta=batch_time.avg * (len(train_loader) - iter) / 60.0,
                loss_text=losses_text.avg,
                loss_kernel=losses_kernels.avg,
                loss_augtext=losses_augtext.avg,
                loss_augkernel=losses_augkernel.avg,
                loss=losses.avg,
                iou_text=ious_text.avg,
                iou_kernel=ious_kernel.avg,
                iou_augtext=ious_augtext.avg,
                iou_augkernel=ious_augkernel.avg,
                loss_dist=losses_dist.avg,
                loss_emb=losses_emb.avg,
                acc_rec=accs_rec.avg,
            )
            print(output_log)
            sys.stdout.flush()

def adjust_learning_rate(optimizer, dataloader, epoch, iter, cfg):
    schedule = cfg.train_cfg.schedule

    if isinstance(schedule, str):
        if schedule == 'polylr':
            cur_iter = epoch * len(dataloader) + iter
            max_iter_num = cfg.train_cfg.epoch * len(dataloader)
            lr = cfg.train_cfg.lr * (1 - float(cur_iter) / max_iter_num) ** 0.9
        elif schedule == 'fixlr':
            lr = cfg.train_cfg.lr
        else:
            raise ValueError('Schedule should be polylr or fixlr!')
    elif isinstance(schedule, tuple):
        lr = cfg.train_cfg.lr
        for i in range(len(schedule)):
            if epoch < schedule[i]:
                break
            lr = lr * 0.1

    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


def save_checkpoint(state, checkpoint_path, cfg):
    file_path = osp.join(checkpoint_path, 'checkpoint.pth.tar')
    torch.save(state, file_path)

    if cfg.data.train.type in ['synth'] or \
            (state['iter'] == 0 and state['epoch'] > 20 and state['epoch'] % 2 == 0):
        file_name = 'checkpoint_%dep.pth.tar' % state['epoch']
        file_path = osp.join(checkpoint_path, file_name)
        torch.save(state, file_path)


def main(args):
    cfg = Config.fromfile(args.config)
    print(json.dumps(cfg._cfg_dict, indent=4))

    if args.checkpoint is not None:
        checkpoint_path = args.checkpoint
    else:
        cfg_name, _ = osp.splitext(osp.basename(args.config))
        checkpoint_path = osp.join('checkpoints', cfg_name)
    if not osp.isdir(checkpoint_path):
        os.makedirs(checkpoint_path)
    print('Checkpoint path: %s.' % checkpoint_path)
    sys.stdout.flush()

    # data loader
    data_loader = build_data_loader(cfg.data.train)
    train_loader = torch.utils.data.DataLoader(
        data_loader,
        batch_size=cfg.data.batch_size,
        shuffle=True,
        num_workers=4,
        drop_last=True,
        pin_memory=True
    )

    # model
    model = build_model(cfg.model)
    model = torch.nn.DataParallel(model).cuda()

    # Check if model has custom optimizer / loss
    if hasattr(model.module, 'optimizer'):
        optimizer = model.module.optimizer
    else:
        if cfg.train_cfg.optimizer == 'SGD':
            optimizer = torch.optim.SGD(model.parameters(), lr=cfg.train_cfg.lr, momentum=0.99, weight_decay=5e-4)
        elif cfg.train_cfg.optimizer == 'Adam':
            optimizer = torch.optim.Adam(model.parameters(), lr=cfg.train_cfg.lr)

    start_epoch = 0
    start_iter = 0
    if hasattr(cfg.train_cfg, 'pretrain'):
        assert osp.isfile(cfg.train_cfg.pretrain), 'Error: no pretrained weights found!'
        print('Finetuning from pretrained model %s.' % cfg.train_cfg.pretrain)
        checkpoint = torch.load(cfg.train_cfg.pretrain)
        model.load_state_dict(checkpoint['state_dict'])
    if args.resume:
        assert osp.isfile(args.resume), 'Error: no checkpoint directory found!'
        print('Resuming from checkpoint %s.' % args.resume)
        checkpoint = torch.load(args.resume)
        start_epoch = checkpoint['epoch']
        start_iter = checkpoint['iter']
        model.load_state_dict(checkpoint['state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer'])

    for epoch in range(start_epoch, cfg.train_cfg.epoch):
        print('\nEpoch: [%d | %d]' % (epoch + 1, cfg.train_cfg.epoch))

        train(train_loader, model, optimizer, epoch, start_iter, cfg)

        state = dict(
            epoch=epoch + 1,
            iter=0,
            state_dict=model.state_dict(),
            optimizer=optimizer.state_dict()
        )
        save_checkpoint(state, checkpoint_path, cfg)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Hyperparams')
    parser.add_argument('config', help='config file path')
    parser.add_argument('--checkpoint', nargs='?', type=str, default=None)
    parser.add_argument('--resume', nargs='?', type=str, default=None)
    args = parser.parse_args()

    main(args)
