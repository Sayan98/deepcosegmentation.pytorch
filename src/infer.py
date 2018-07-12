"""
Test SegNet based Siamese network

usage: infer.py --dataset_root /home/SharedData/intern_sayan/iCoseg/ \
                --img_dir images \
                --mask_dir ground_truth \
                --checkpoint_path /home/SharedData/intern_sayan/PASCAL_coseg/deepcoseg_model_best.pth \
                --output_dir ./results \
                --gpu 0

author - Sayan Goswami
email  - sayan.goswami.106@gmail.com
"""

import argparse
from dataset import iCosegDataset, PASCALVOCCosegDataset
from model import SiameseSegNet
import numpy as np
import os
import pdb
from tensorboardX import SummaryWriter
import time
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
import torchvision
from tqdm import tqdm

#-----------#
# Arguments #
#-----------#

parser = argparse.ArgumentParser(description='Train a SegNet model')

parser.add_argument('--dataset_root', required=True)
parser.add_argument('--img_dir', required=True)
parser.add_argument('--mask_dir', required=True)
parser.add_argument('--checkpoint_path', required=True)
parser.add_argument('--output_dir', required=True)
parser.add_argument('--gpu', default=None)

args = parser.parse_args()

#-----------#
# Constants #
#-----------#

## Debug

DEBUG = False


## Dataset
BATCH_SIZE = 2 * 1 # two images at a time for Siamese net
INPUT_CHANNELS = 3 # RGB
OUTPUT_CHANNELS = 1 # BG + FG channel

## Inference
CUDA = args.gpu

## Output Dir
OUTPUT_DIR = args.output_dir

os.system(f"rm -r {OUTPUT_DIR}")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def infer():
    model.eval()

    intersection, union, precision = 0, 0, 0
    correct_predictions, total_predictions = 0, 0

    t_start = time.time()

    for batch_idx, batch in tqdm(enumerate(dataloader)):
        images = batch["image"].type(FloatTensor)
        labels = batch["label"].type(LongTensor)
        masks  = batch["mask"].type(FloatTensor)

        # pdb.set_trace()

        pairwise_images = [(images[2*idx], images[2*idx+1]) for idx in range(BATCH_SIZE//2)]
        pairwise_labels = [(labels[2*idx], labels[2*idx+1]) for idx in range(BATCH_SIZE//2)]
        pairwise_masks  = [(masks[2*idx], masks[2*idx+1]) for idx in range(BATCH_SIZE//2)]

        # pdb.set_trace()

        imagesA, imagesB = zip(*pairwise_images)
        labelsA, labelsB = zip(*pairwise_labels)
        masksA, masksB = zip(*pairwise_masks)

        # pdb.set_trace()

        imagesA, imagesB = torch.stack(imagesA), torch.stack(imagesB)
        labelsA, labelsB = torch.stack(labelsA), torch.stack(labelsB)
        masksA, masksB = torch.stack(masksA), torch.stack(masksB)

        # pdb.set_trace()

        eq_labels = []

        for idx in range(BATCH_SIZE//2):
            if torch.equal(labelsA[idx], labelsB[idx]):
                eq_labels.append(torch.ones(1).type(FloatTensor))
            else:
                eq_labels.append(torch.zeros(1).type(FloatTensor))

        eq_labels = torch.stack(eq_labels)

        # pdb.set_trace()

        masksA = masksA * eq_labels
        masksB = masksB * eq_labels


        imagesA_v = torch.autograd.Variable(imagesA.type(FloatTensor))
        imagesB_v = torch.autograd.Variable(imagesB.type(FloatTensor))


        pmapA, pmapB, similarity = model(imagesA_v, imagesB_v)


        # squeeze channels
        pmapA_sq = pmapA.squeeze(1)
        pmapB_sq = pmapB.squeeze(1)

        # pdb.set_trace()

        res_images, res_masks, gt_masks = [], [], []

        for idx in range(BATCH_SIZE//2):
            res_images.append(imagesA[idx])
            res_images.append(imagesB[idx])

            res_masks.append((pmapA_sq * similarity[idx]).reshape(1, 512, 512))
            res_masks.append((pmapB_sq * similarity[idx]).reshape(1, 512, 512))

            gt_masks.append(masksA[idx].reshape(1, 512, 512))
            gt_masks.append(masksB[idx].reshape(1, 512, 512))

        # pdb.set_trace()

        images_T = torch.stack(res_images)
        masks_T = torch.stack(res_masks)
        gt_masks_T = torch.stack(gt_masks)


        # metrics - IoU & precision
        intersection_a, intersection_b, union_a, union_b, precision_a, precision_b = 0, 0, 0, 0, 0, 0

        for idx in range(BATCH_SIZE//2):
            # pdb.set_trace()

            pred_maskA = np.uint64(pmapA_sq[idx].detach().cpu().numpy())
            pred_maskB = np.uint64(pmapB_sq[idx].detach().cpu().numpy())

            masksA_cpu = np.uint64(masksA[idx].cpu().numpy())
            masksB_cpu = np.uint64(masksB[idx].cpu().numpy())

            intersection_a += np.sum(pred_maskA & masksA_cpu)
            intersection_b += np.sum(pred_maskB & masksB_cpu)

            union_a += np.sum(pred_maskA | masksA_cpu)
            union_b += np.sum(pred_maskB | masksB_cpu)

            precision_a += np.sum(pred_maskA == masksA_cpu)
            precision_b += np.sum(pred_maskB == masksB_cpu)

        intersection += intersection_a + intersection_b
        union += union_a + union_b

        precision += (precision_a / (512 * 512)) + (precision_b / (512 * 512))

        correct_predictions += np.sum((similarity.detach().cpu().numpy() >= 0.5) == eq_labels.detach().cpu().numpy())
        total_predictions += BATCH_SIZE//2

        # pdb.set_trace()

        torchvision.utils.save_image(images_T, os.path.join(OUTPUT_DIR, f"batch_{batch_idx}_images.png"), nrow=2)
        torchvision.utils.save_image(masks_T, os.path.join(OUTPUT_DIR, f"batch_{batch_idx}_masks.png"), nrow=2)
        torchvision.utils.save_image(gt_masks_T, os.path.join(OUTPUT_DIR, f"batch_{batch_idx}_gt_masks.png"), nrow=2)

    delta = time.time() - t_start

    print(f"""\nTime elapsed: [{delta} secs]
          Precision : [{precision/(len(dataloader) * BATCH_SIZE)}]
          IoU : [{intersection/union}]
          Classifier Accuracy: [{correct_predictions/total_predictions}]""")


if __name__ == "__main__":
    root_dir = args.dataset_root

    image_dir = os.path.join(root_dir, args.img_dir)
    mask_dir = os.path.join(root_dir, args.mask_dir)

    iCoseg_dataset = iCosegDataset(image_dir=image_dir,
                                   mask_dir=mask_dir)

    dataloader = DataLoader(iCoseg_dataset, batch_size=BATCH_SIZE, shuffle=False, num_workers=4, drop_last=True)

    #-------------#
    #    Model    #
    #-------------#

    model = SiameseSegNet(input_channels=INPUT_CHANNELS,
                          output_channels=OUTPUT_CHANNELS,
                          gpu=CUDA)

    if DEBUG:
        print(model)

    FloatTensor = torch.FloatTensor
    LongTensor = torch.LongTensor

    if CUDA is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu

        model = model.cuda()

        FloatTensor = torch.cuda.FloatTensor
        LongTensor = torch.cuda.LongTensor

    model.load_state_dict(torch.load(args.checkpoint_path))

    #------------#
    #    Test    #
    #------------#

    infer()
