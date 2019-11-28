from functools import partial

import numpy as np
import torch
from sklearn.neighbors import NearestNeighbors

from deepsmlm.generic import emitter as emitter


class GreedyHungarianMatching:
    """
    A class to match outputs and targets based on pairwise distance matrix
    """

    def __init__(self, dist_lat:float = None, dist_vol: float = None):
        """
        :param dist_lat: (float) lateral distance threshold
        :param dist_vol: (float) volumetric distance threshold
        """
        self.dist_thresh = None
        self._match_dims = None

        if ((dist_lat is not None) and (dist_vol is not None)) or ((dist_lat is None) and (dist_vol is None)):
            raise ValueError("You need to specify exactly exclusively either dist_lat or dist_vol.")

        if dist_lat is not None:
            self.dist_thresh = dist_lat
            self._match_dims = 2
        elif dist_vol is not None:
            self.dist_thresh = dist_vol
            self._match_dims = 2

        self.cdist_kernel = partial(torch.cdist, p=2)  # does not take the square root

    @staticmethod
    def parse(param):
        return GreedyHungarianMatching(dist_lat=param['Evaluation']['dist_lat'],
                                       dist_vol=param['Evaluation']['dist_vol'])

    @staticmethod
    def rule_out_dist_match(dists, threshold):
        match_list = []
        while dists.min() < threshold:
            ix = np.unravel_index(dists.argmin(), dists.shape)
            dists[ix[0]] = float('inf')
            dists[:, ix[1]] = float('inf')

            match_list.append(ix)
        return torch.tensor(match_list)

    def assign_kernel(self, out, tar):
        """
        Assigns out and tar, blind to a frame index. Therefore, split in frames beforehand
        :param out:
        :param tar:
        :return:
        """
        """If no emitter has been found, all are false negatives. No tp, no fp."""
        if out.num_emitter == 0:
            tp, fp, tp_match = emitter.EmptyEmitterSet(), emitter.EmptyEmitterSet(), emitter.EmptyEmitterSet()
            fn = tar
            return tp, fp, fn, tp_match

        """If there were no positives, no tp, no fn, all fp, no match."""
        if tar.num_emitter == 0:
            tp, fn, tp_match = emitter.EmptyEmitterSet(), emitter.EmptyEmitterSet(), emitter.EmptyEmitterSet()
            fp = out
            return tp, fp, fn, tp_match

        if self._match_dims == 2:
            dists = self.cdist_kernel(out.xyz[:, :2], tar.xyz[:, :2])
        elif self._match_dims == 3:
            dists = self.cdist_kernel(out.xyz, tar.xyz)

        match_ix = self.rule_out_dist_match(dists, self.dist_thresh).numpy()
        all_ix_out = np.arange(out.num_emitter)
        all_ix_tar = np.arange(tar.num_emitter)

        tp = out.get_subset(match_ix[:, 0])
        tp_match = tar.get_subset(match_ix[:, 1])

        fp_ix = torch.from_numpy(np.setdiff1d(all_ix_out, match_ix[:, 0]))
        fn_ix = torch.from_numpy(np.setdiff1d(all_ix_tar, match_ix[:, 1]))

        fp = out.get_subset(fp_ix)
        fn = tar.get_subset(fn_ix)

        return tp, fp, fn, tp_match

    def forward(self, output, target):
        """
        Assign outputs to targets. Make sure that the frame indices of target and output match.

        :param output:
        :param target:
        :return:
        """

        """Split in Frames based on the target"""
        frame_low = int(target.frame_ix.min().item())
        frame_high = int(target.frame_ix.max().item())

        out_pframe = output.split_in_frames(frame_low, frame_high)
        tar_pframe = target.split_in_frames(frame_low, frame_high)

        tpl, fpl, fnl, tpml = [], [], [], []  # true positive list, false positive list, false neg. ...

        """Assign the emitters framewise"""
        for i in range(out_pframe.__len__()):
            tp, fp, fn, tp_match = self.assign_kernel(out_pframe[i], tar_pframe[i])
            tpl.append(tp)
            fpl.append(fp)
            fnl.append(fn)
            tpml.append(tp_match)

        """Concat them back"""
        tp = emitter.EmitterSet.cat_emittersets(tpl)
        fp = emitter.EmitterSet.cat_emittersets(fpl)
        fn = emitter.EmitterSet.cat_emittersets(fnl)
        tp_match = emitter.EmitterSet.cat_emittersets(tpml)

        """Let tp and tp_match share the same id's"""
        if (tp_match.id == -1).all().item():
            tp_match.id = torch.arange(tp_match.num_emitter)
        tp.id = tp_match.id

        return tp, fp, fn, tp_match


class NNMatching:
    """
    A class to match outputs and targets based on 1neighbor nearest neighbor classifier.
    """
    def __init__(self, dist_lat=2.5, dist_ax=500, match_dims=3):
        """

        :param dist_lat: (float) lateral distance threshold
        :param dist_ax: (float) axial distance threshold
        :param match_dims: should we match the emitters only in 2D or also 3D
        """
        self.dist_lat_thresh = dist_lat
        self.dist_ax_thresh = dist_ax
        self.match_dims = match_dims

        self.nearest_neigh = NearestNeighbors(n_neighbors=1, metric='minkowski', p=2)

        if self.match_dims not in [2, 3]:
            raise ValueError("You must compare in either 2 or 3 dimensions.")

    @staticmethod
    def parse(param: dict):
        """

        :param param: parameter dict
        :return:
        """
        return NNMatching(**param['Evaluation'])

    def forward(self, output, target):
        """Forward arbitrary output and target set. Does not care about the frame_ix.

        :param output: (emitterset)
        :param target: (emitterset)
        :return tp, fp, fn, tp_match: (emitterset) true positives, false positives, false negatives, ground truth matched to the true pos
        """
        xyz_tar = target.xyz.numpy()
        xyz_out = output.xyz.numpy()

        if self.match_dims == 2:
            xyz_tar_ = xyz_tar[:, :2]
            xyz_out_ = xyz_out[:, :2]
        else:
            xyz_tar_ = xyz_tar
            xyz_out_ = xyz_out

        """If no emitter has been found, all are false negatives. No tp, no fp."""
        if xyz_out_.shape[0] == 0:
            tp = emitter.EmptyEmitterSet()
            fp = emitter.EmptyEmitterSet()
            fn = target
            tp_match = emitter.EmptyEmitterSet()

            return tp, fp, fn, tp_match

        if xyz_tar_.shape[0] != 0:
            nbrs = self.nearest_neigh.fit(xyz_tar_)

        else:
            """If there were no positives, no tp, no fn, all fp, no match."""
            tp = emitter.EmptyEmitterSet()
            fn = emitter.EmptyEmitterSet()
            fp = output
            tp_match = emitter.EmptyEmitterSet()

            return tp, fp, fn, tp_match

        distances_nn, indices = nbrs.kneighbors(xyz_out_)

        distances_nn = distances_nn.squeeze()
        indices = np.atleast_1d(indices.squeeze())

        xyz_match = target.get_subset(indices).xyz.numpy()

        # calculate distances lateral and axial seperately
        dist_lat = np.linalg.norm(xyz_out[:, :2] - xyz_match[:, :2], axis=1, ord=2)
        dist_ax = np.linalg.norm(xyz_out[:, [2]] - xyz_match[:, [2]], axis=1, ord=2)

        # remove those which are too far
        if self.match_dims == 3:
            is_tp = (dist_lat <= self.dist_lat_thresh) * (dist_ax <= self.dist_ax_thresh)
        elif self.match_dims == 2:
            is_tp = (dist_lat <= self.dist_lat_thresh)

        is_fp = ~is_tp

        indices[is_fp] = -1
        indices_cleared = indices[indices != -1]

        # create indices of targets
        tar_ix = np.arange(target.num_emitter)
        # remove indices which were found
        fn_ix = np.setdiff1d(tar_ix, indices)

        is_tp = torch.from_numpy(is_tp.astype(np.uint8)).type(torch.BoolTensor)
        is_fp = torch.from_numpy(is_fp.astype(np.uint8)).type(torch.BoolTensor)
        fn_ix = torch.from_numpy(fn_ix)

        tp = output.get_subset(is_tp)
        fp = output.get_subset(is_fp)
        fn = target.get_subset(fn_ix)
        tp_match = target.get_subset(indices_cleared)

        return tp, fp, fn, tp_match