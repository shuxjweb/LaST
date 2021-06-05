# encoding: utf-8

import argparse
import os
import sys
import torch
import numpy as np
from torch.backends import cudnn
sys.path.append('.')
from data import make_data_loader_path as make_data_loader
from engine.trainer import do_train_strong_path as do_train
from modeling import build_model
from layers import make_loss_with_triplet_entropy
from solver import make_optimizer, WarmupMultiStepLR
from engine.inference import inference
import datetime


def load_network_pretrain(model, cfg):
    path = os.path.join(cfg.logs_dir, 'checkpoint.pth')
    if not os.path.exists(path):
        return model, 0, 0.0
    pre_dict = torch.load(path)
    model.load_state_dict(pre_dict['state_dict'])
    start_epoch = pre_dict['epoch']
    best_acc = pre_dict['best_acc']
    print('start_epoch:', start_epoch)
    print('best_acc:', best_acc)
    return model, start_epoch, best_acc


def main(cfg):
    # prepare dataset
    dataset, train_loader, test_loader, num_query, num_classes = make_data_loader(cfg)

    # prepare model 
    model = build_model(num_classes, 'base')        # num_classes=751
    model = torch.nn.DataParallel(model).cuda() if torch.cuda.is_available() else model

    loss_func = make_loss_with_triplet_entropy(cfg, num_classes)  # modified by gu
    optimizer = make_optimizer(cfg, model)
    scheduler = WarmupMultiStepLR(optimizer, cfg.steps, cfg.gamma, cfg.warmup_factor, cfg.warmup_iters, cfg.warmup_method)

    if cfg.train == 1:
        start_epoch = 0
        acc_best = 0.0
        if cfg.resume == 1:
            model, start_epoch, acc_best = load_network_pretrain(model, cfg)

        do_train(cfg, model, train_loader, test_loader, optimizer, scheduler, loss_func, num_query, start_epoch, acc_best)
    else:
        # Test
        last_model_wts = torch.load(os.path.join(cfg.logs_dir, 'checkpoint_best.pth'))
        model.load_state_dict(last_model_wts['state_dict'])
        mAP, cmc1, cmc5, cmc10, cmc20, feat_dict = inference(model, test_loader, num_query, True)

        start_time = datetime.datetime.now()
        start_time = '%4d:%d:%d-%2d:%2d:%2d' % (start_time.year, start_time.month, start_time.day, start_time.hour, start_time.minute, start_time.second)
        print('{} - Final: cmc1: {:.1%} cmc5: {:.1%} cmc10: {:.1%} cmc20: {:.1%} mAP: {:.1%}\n'.format(start_time, cmc1, cmc5, cmc10, cmc20, mAP))

        path_f = os.path.join(cfg.logs_dir, 'market_feat_test.npy')
        feats = torch.stack([feat_dict[name] for name, _, _ in test_loader.dataset.dataset]).cpu().data.numpy()  # [70264, 2048]
        np.save(path_f, feats)


if __name__ == '__main__':
    gpu_id = 0
    os.environ['CUDA_VISIBLE_DEVICES'] = str(gpu_id)
    cudnn.benchmark = True

    parser = argparse.ArgumentParser(description="ReID Baseline Training")

    # DATA
    parser.add_argument('--batch_size', type=int, default=64)
    parser.add_argument('--img_per_id', type=int, default=4)
    parser.add_argument('--batch_size_test', type=int, default=128)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--height', type=int, default=256)
    parser.add_argument('--width', type=int, default=128)
    parser.add_argument('--height_mask', type=int, default=256)
    parser.add_argument('--width_mask', type=int, default=128)


    # MODEL
    parser.add_argument('--features', type=int, default=128)
    parser.add_argument('--dropout', type=float, default=0.0)

    # OPTIMIZER
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--lr', type=float, default=0.00035)
    parser.add_argument('--lr_center', type=float, default=0.5)
    parser.add_argument('--center_loss_weight', type=float, default=0.0005)
    parser.add_argument('--steps', type=list, default=[40, 100])
    parser.add_argument('--gamma', type=float, default=0.1)
    parser.add_argument('--cluster_margin', type=float, default=0.3)
    parser.add_argument('--bias_lr_factor', type=float, default=1.0)
    parser.add_argument('--weight_decay', type=float, default=5e-4)
    parser.add_argument('--weight_decay_bias', type=float, default=5e-4)
    parser.add_argument('--range_k', type=float, default=2)
    parser.add_argument('--range_margin', type=float, default=0.3)
    parser.add_argument('--range_alpha', type=float, default=0)
    parser.add_argument('--range_beta', type=float, default=1)
    parser.add_argument('--range_loss_weight', type=float, default=1)
    parser.add_argument('--warmup_factor', type=float, default=0.01)
    parser.add_argument('--warmup_iters', type=float, default=10)
    parser.add_argument('--warmup_method', type=str, default='linear')
    parser.add_argument('--margin', type=float, default=0.3)
    parser.add_argument('--optimizer_name', type=str, default="Adam")
    parser.add_argument('--momentum', type=float, default=0.9)

    # TRAINER
    parser.add_argument('--max_epochs', type=int, default=120)
    parser.add_argument('--train', type=int, default=1)  # change train or test mode
    parser.add_argument('--resume', type=int, default=0)
    parser.add_argument('--num_works', type=int, default=8)

    # misc
    working_dir = os.path.dirname(os.path.abspath(__file__))
    parser.add_argument('--dataset', type=str, default='market1501')
    parser.add_argument('--data_dir', type=str, default='/data/shuxj/data/PReID/Market/market1501/')

    parser.add_argument('--logs_dir', type=str, default=os.path.join(working_dir, 'logs/20210508_market_bot'))

    cfg = parser.parse_args()
    if not os.path.exists(cfg.logs_dir):
        os.makedirs(cfg.logs_dir)

    main(cfg)
