import os
import sys
import torch.nn.parallel
import torch.optim
import torch.utils.data
import torch.utils.data.distributed
from torch import nn
from args import args
import datetime
import copy
from data.Data import CIFAR10, CIFAR100
from model.samll_resnet import resnet56
from trainer.amp_trainer_dali import train_ImageNet, validate_ImageNet
from trainer.trainer import validate, train
from utils.get_dataset import get_dataset
from utils.get_model import get_model
from utils.utils import set_random_seed, set_gpu, Logger, get_logger, get_lr
from utils.warmup_lr import cosine_lr

# python KD.py --gpu 0 --arch cvgg8_bn --set cifar10 --lr 0.01 --batch_size 256 --weight_decay 0.005 --epochs 600   --num_classes 10  --finetune
# python KD.py --gpu 0 --arch resnet56_KD_14 --set cifar10 --lr 0.01 --batch_size 256 --weight_decay 0.005 --epochs 600   --num_classes 10  --finetune
# python KD.py --gpu 2 --arch ResNet50_13 --set imagenet_dali --lr 0.01 --batch_size 256 --weight_decay 0.0005 --epochs 120   --num_classes 1000  --finetune
# python KD.py --gpu 3 --arch resnet56_KD_19_c100 --set cifar100 --lr 0.01 --batch_size 256 --weight_decay 0.005 --epochs 400   --num_classes 100  --finetune

def main():
    print(args)
    sys.stdout = Logger('print process.log', sys.stdout)

    if args.random_seed is not None:
        set_random_seed(args.random_seed)

    main_worker(args)


def main_worker(args):
    now = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
    if not os.path.isdir('pretrained_model/' + args.arch + '/' + args.set):
        os.makedirs('pretrained_model/' + args.arch + '/' + args.set, exist_ok=True)
    logger = get_logger('pretrained_model/' + args.arch + '/' + args.set + '/logger' + now + '.log')
    logger.info(args.arch)
    logger.info(args.set)
    logger.info(args.batch_size)
    logger.info(args.weight_decay)
    logger.info(args.lr)
    logger.info(args.epochs)
    logger.info(args.lr_decay_step)
    logger.info(args.num_classes)

    model_s = get_model(args)
    model_s = set_gpu(args, model_s)

    logger.info(model_s)
    criterion = nn.CrossEntropyLoss().cuda()
    data = get_dataset(args)

    optimizer = torch.optim.SGD(model_s.parameters(), lr=args.lr, momentum=args.momentum, weight_decay=args.weight_decay)
    # # multi lr
    # lr_decay_step = list(map(int, args.lr_decay_step.split(',')))
    # scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, milestones=lr_decay_step, gamma=0.1)

    scheduler = cosine_lr(optimizer, args)

    best_acc1 = 0.0
    best_acc5 = 0.0
    best_train_acc1 = 0.0
    best_train_acc5 = 0.0

    # create recorder
    args.start_epoch = args.start_epoch or 0
    best_ckpt = None

    # Start training
    for epoch in range(args.start_epoch, args.epochs):
        scheduler(epoch, iteration=None)
        cur_lr = get_lr(optimizer)
        logger.info(f"==> CurrentLearningRate: {cur_lr}")
        if args.set == 'imagenet_dali':
            # for imagenet
            train_acc1, train_acc5 = train_ImageNet(data.train_loader, model_s, criterion, optimizer, epoch, args)
            acc1, acc5 = validate_ImageNet(data.val_loader, model_s, criterion, args)
        else:
            #  for small datasets
            train_acc1, train_acc5 = train(data.train_loader, model_s, criterion, optimizer, epoch, args)
            acc1, acc5 = validate(data.val_loader, model_s, criterion, args)

        # remember best acc@1 and save checkpoint
        is_best = acc1 > best_acc1
        best_acc1 = max(acc1, best_acc1)
        best_acc5 = max(acc5, best_acc5)
        best_train_acc1 = max(train_acc1, best_train_acc1)
        best_train_acc5 = max(train_acc5, best_train_acc5)
        save = ((epoch % args.save_every) == 0) and args.save_every > 0
        if is_best or save or epoch == args.epochs - 1:
            if is_best:
                best_ckpt = copy.deepcopy(model_s.state_dict())
                logger.info(best_acc1)

        # scheduler.step()

    torch.save(best_ckpt, 'pretrained_model/' + args.arch + '/' + args.set + "/K5_{}_{}_{}.pt".format(args.arch, args.set, best_acc1))

if __name__ == "__main__":
    # setup: python KD.py --gpu 3 --arch resnet56_KD_12 --set cifar10 --lr 0.01 --batch_size 256 --weight_decay 0.005 --epochs 150 --lr_decay_step 50,100  --num_classes 10  --finetune
    main()



