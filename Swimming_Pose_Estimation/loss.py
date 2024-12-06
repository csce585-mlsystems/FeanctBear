# ------------------------------------------------------------------------------
# Copyright (c) Microsoft
# Licensed under the MIT License.
# imported code written Bin Xiao (Bin.Xiao@microsoft.com)
# modified by Mark Shperkin
# ------------------------------------------------------------------------------
import torch
import torch.nn as nn


class JointsMSELoss(nn.Module):
    def __init__(self, use_target_weight):
        super(JointsMSELoss, self).__init__()
        self.criterion = nn.MSELoss(reduction='mean')
        self.use_target_weight = use_target_weight

    def forward(self, output, target, target_weight):
        batch_size = output.size(0)
        num_joints = output.size(1)
        heatmaps_pred = output.reshape((batch_size, num_joints, -1)).split(1, 1)
        heatmaps_gt = target.reshape((batch_size, num_joints, -1)).split(1, 1)
        loss = 0

        for idx in range(num_joints):
            # extract heatmap predictions and ground truths for the current joint with shape [batch_size, flattened_size]
            heatmap_pred = heatmaps_pred[idx].squeeze()
            heatmap_gt = heatmaps_gt[idx].squeeze()
            
            # expand target_weight to match the shape of heatmap_pred with shape [batch_size, 1]
            target_weight_expanded = target_weight[:, idx].unsqueeze(1)
            
            # apply target_weight during loss computation
            if self.use_target_weight:
                loss += 0.5 * self.criterion(
                    heatmap_pred * target_weight_expanded,
                    heatmap_gt * target_weight_expanded
                )
            else:
                loss += 0.5 * self.criterion(heatmap_pred, heatmap_gt)

        return loss / num_joints


class JointsOHKMMSELoss(nn.Module):
    def __init__(self, use_target_weight, topk=8):
        super(JointsOHKMMSELoss, self).__init__()
        self.criterion = nn.MSELoss(reduction='none')
        self.use_target_weight = use_target_weight
        self.topk = topk

    def ohkm(self, loss):
        ohkm_loss = 0.
        for i in range(loss.size()[0]):
            sub_loss = loss[i]
            topk_val, topk_idx = torch.topk(
                sub_loss, k=self.topk, dim=0, sorted=False
            )
            tmp_loss = torch.gather(sub_loss, 0, topk_idx)
            ohkm_loss += torch.sum(tmp_loss) / self.topk
        ohkm_loss /= loss.size()[0]
        return ohkm_loss

    def forward(self, output, target, target_weight):
        batch_size = output.size(0)
        num_joints = output.size(1)
        heatmaps_pred = output.reshape((batch_size, num_joints, -1)).split(1, 1)  # [B, K, H*W]
        heatmaps_gt = target.reshape((batch_size, num_joints, -1)).split(1, 1)  # [B, K, H*W]

        loss = []
        for idx in range(num_joints):
            heatmap_pred = heatmaps_pred[idx].squeeze()  # [B, H*W]
            heatmap_gt = heatmaps_gt[idx].squeeze()  # [B, H*W]

            if self.use_target_weight:
                # expand target_weight to match spatial dimensions
                target_weight_expanded = target_weight[:, idx].unsqueeze(1)  # [B, 1]
                target_weight_expanded = target_weight_expanded.expand_as(heatmap_pred)  # [B, H*W]

                # apply target weight to both predictions and ground truth
                weighted_pred = heatmap_pred * target_weight_expanded
                weighted_gt = heatmap_gt * target_weight_expanded

                loss.append(0.5 * self.criterion(weighted_pred, weighted_gt))
            else:
                loss.append(0.5 * self.criterion(heatmap_pred, heatmap_gt))

        # compute mean loss per joint and concatenate
        loss = [l.mean(dim=1).unsqueeze(dim=1) for l in loss]  # [B, 1] for each joint
        loss = torch.cat(loss, dim=1)  # [B, K]

        return self.ohkm(loss)