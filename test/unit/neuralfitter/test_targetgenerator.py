import numpy as np
import pytest
import torch


import decode.simulation.psf_kernel as psf_kernel
from decode.emitter import emitter
from decode.generic import test_utils as tutil
from decode.neuralfitter import target_generator


# ToDo: Deprecate this complicated style test
class TestTargetGenerator:
    @pytest.fixture()
    def targ(self):
        """
        Setup dummy target generator for inheritors.

        """

        class DummyTarget(target_generator.TargetGenerator):
            def __init__(self, xextent, yextent, img_shape):
                super().__init__(ix_low=0, ix_high=0)
                self.xextent = xextent
                self.yextent = yextent
                self.img_shape = img_shape

                self.delta = psf_kernel.DeltaPSF(
                    xextent=self.xextent, yextent=self.yextent, img_shape=self.img_shape
                )

            def forward(self, em, bg=None, ix_low=None, ix_high=None):
                em, ix_low, ix_high = self._filter_forward(em, ix_low, ix_high)

                return self.delta.forward(
                    em.xyz, em.phot, None, ix_low, ix_high
                ).unsqueeze(1)

        xextent = (-0.5, 63.5)
        yextent = (-0.5, 63.5)
        img_shape = (64, 64)
        return DummyTarget(xextent, yextent, img_shape)

    @pytest.fixture()
    def fem(self):
        return emitter.EmitterSet(
            xyz=torch.tensor([[0.0, 0.0, 0.0]]),
            phot=torch.Tensor([1.0]),
            frame_ix=torch.tensor([0]),
            xy_unit="px",
        )

    def test_shape(self, targ, fem):
        """
        Tests the frame_shape of the target output

        Args:
            targ:
            fem:

        """

        out = targ.forward(fem)

        """Tests"""
        assert out.dim() == 4, "Wrong dimensionality."
        assert out.size()[-2:] == torch.Size(targ.img_shape), "Wrong output shape."

    @pytest.mark.parametrize("ix_low,ix_high", [(0, 0), (-1, 1)])
    @pytest.mark.parametrize(
        "em_data", [emitter.factory(0, xy_unit="px"), emitter.factory(10, xy_unit="px")]
    )
    def test_default_range(self, targ, ix_low, ix_high, em_data):
        targ.ix_low = ix_low
        targ.ix_high = ix_high

        out = targ.forward(em_data)

        """Assertions"""
        assert out.size(0) == ix_high - ix_low + 1


class TestUnifiedEmbeddingTarget(TestTargetGenerator):
    @pytest.fixture()
    def targ(self):
        xextent = (-0.5, 63.5)
        yextent = (-0.5, 63.5)
        img_shape = (64, 64)

        return target_generator.UnifiedEmbeddingTarget(
            xextent, yextent, img_shape, roi_size=5, ix_low=0, ix_high=5
        )

    @pytest.fixture()
    def random_emitter(self):
        em = emitter.factory(1000)
        em.frame_ix = torch.randint_like(em.frame_ix, low=-20, high=30)

        return em

    def test_central_px(self, targ, random_emitter):
        """
        Check whether central pixels agree with delta function are correct.
        """

        x_ix, y_ix = targ._delta_psf.search_bin_index(random_emitter.xyz)

        assert (x_ix == random_emitter.xyz[:, 0].round().long()).all()
        assert (y_ix == random_emitter.xyz[:, 1].round().long()).all()

    @pytest.mark.parametrize("roi_size", torch.tensor([1, 3, 5, 7]))
    def test_roi_px(self, targ, random_emitter, roi_size):

        targ.__init__(
            xextent=targ.xextent,
            yextent=targ.yextent,
            img_shape=targ.img_shape,
            roi_size=roi_size,
            ix_low=targ.ix_low,
            ix_high=targ.ix_high,
        )

        # mask, ix = targ._get_central_px(random_emitter.xyz, random_emitter.frame_ix)
        x_ix, y_ix = targ._delta_psf.search_bin_index(random_emitter.xyz_px)
        batch_ix = random_emitter.frame_ix
        batch_ix, x_ix, y_ix, off_x, off_y, id = targ._get_roi_px(batch_ix, x_ix, y_ix)

        assert (x_ix >= 0).all()
        assert (y_ix >= 0).all()
        assert (x_ix <= 63).all()
        assert (y_ix <= 63).all()
        assert batch_ix.size() == off_x.size()
        assert off_x.size() == off_y.size()

        expct_vals = torch.arange(
            -(targ._roi_size - 1) // 2, (targ._roi_size - 1) // 2 + 1
        )

        assert (off_x.unique() == expct_vals).all()
        assert (off_y.unique() == expct_vals).all()

    def test_forward_handcrafted(self, targ):
        """Test a couple of handcrafted cases"""

        # one emitter outside fov the other one inside
        em_set = emitter.factory(
            xyz=torch.tensor([[-50.0, 0.0, 0.0], [15.1, 19.6, 250.0]]), xy_unit="px"
        )
        em_set.phot = torch.tensor([5.0, 4.0])

        out = targ.forward(em_set)[0]  # single frame
        assert tutil.tens_almeq(
            out[:, 15, 20], torch.tensor([1.0, 4.0, 0.1, -0.4, 250.0]), 1e-5
        )
        assert tutil.tens_almeq(
            out[:, 16, 20], torch.tensor([0.0, 4.0, -0.9, -0.4, 250.0]), 1e-5
        )
        assert tutil.tens_almeq(
            out[:, 15, 21], torch.tensor([0.0, 4.0, 0.1, -1.4, 250.0]), 1e-5
        )

    def test_forward_statistical(self, targ):

        n = 1000

        xyz = torch.zeros((n, 3))
        xyz[:, 0] = torch.linspace(-10, 78.0, n)
        xyz[:, 1] = 30.0

        frame_ix = torch.arange(n)

        em = emitter.EmitterSet(xyz, torch.ones_like(xyz[:, 0]), frame_ix, xy_unit="px")

        out = targ.forward(em, None, 0, n - 1)

        assert (out[:, 0, :, 29] == 0).all()
        assert (out[:, 0, :, 31] == 0).all()
        assert (out[(xyz[:, 0] < -0.5) * (xyz[:, 0] >= 63.5)] == 0).all()
        assert (
            out.nonzero()[:, 0].unique()
            == frame_ix[(xyz[:, 0] >= -0.5) * (xyz[:, 0] < 63.5)]
        ).all()

    def test_forward_different_impl(self, targ):
        """
        Test the implementation with a slow for loop

        Args:
            targ:

        Returns:

        """

        n = 5000
        xyz = torch.rand(n, 3) * 100

        # move them a bit away from zero for this test (otherwise it might fail)
        ix_close_zero = xyz.abs() < 1e-6
        xyz[ix_close_zero] = xyz[ix_close_zero] + 0.01

        phot = torch.rand_like(xyz[:, 0])
        frame_ix = torch.arange(n)

        em = emitter.EmitterSet(xyz, phot, frame_ix, xy_unit="px")

        out = targ.forward(em, None, 0, n - 1)

        non_zero_detect = out[:, [0]].nonzero()

        for i in range(non_zero_detect.size(0)):
            for x in range(-(targ._roi_size - 1) // 2, (targ._roi_size - 1) // 2 + 1):
                for y in range(
                    -(targ._roi_size - 1) // 2, (targ._roi_size - 1) // 2 + 1
                ):
                    ix_n = non_zero_detect[i, 0]
                    ix_x = torch.clamp(non_zero_detect[i, -2] + x, 0, 63)
                    ix_y = torch.clamp(non_zero_detect[i, -1] + y, 0, 63)
                    assert (
                        out[ix_n, 2, ix_x, ix_y] != 0
                    )  # would only fail if either x or y are exactly % 1 == 0


class Test4FoldTarget(TestTargetGenerator):
    @pytest.fixture()
    def targ(self):
        xextent = (-0.5, 63.5)
        yextent = (-0.5, 63.5)
        img_shape = (64, 64)

        return target_generator.FourFoldEmbedding(
            xextent=xextent,
            yextent=yextent,
            img_shape=img_shape,
            rim_size=0.125,
            roi_size=3,
            ix_low=0,
            ix_high=5,
        )

    def test_filter_rim(self, targ):

        xy = torch.tensor([[0.1, 0.9], [45.2, 47.8], [0.13, 0.9]]) - 0.5
        ix_tar = torch.tensor([0, 1, 0]).bool()

        ix_out = targ._filter_rim(xy, (-0.5, -0.5), 0.125, (1.0, 1.0))

        assert (ix_out == ix_tar).all()

    def test_forward(self, targ):

        em = emitter.EmitterSet(
            xyz=torch.tensor(
                [[0.0, 0.0, 0.0], [0.49, 0.0, 0.0], [0.0, 0.49, 0.0], [0.49, 0.49, 0.0]]
            ),
            phot=torch.ones(4),
            frame_ix=torch.tensor([0, 1, 2, 3]),
            xy_unit="px",
        )

        tar_out = targ.forward(em, None)

        assert tar_out.size() == torch.Size([6, 20, 64, 64])
        # Negative samples
        assert tar_out[1, 0, 0, 0] == 0.0
        # Positive Samples
        assert (
            tar_out[[0, 1, 2, 3], [0, 5, 10, 15], 0, 0]
            == torch.tensor([1.0, 1.0, 1.0, 1.0])
        ).all()

    @pytest.mark.parametrize("axis", [0, 1, "diag"])
    def test_forward_systematic(self, targ, axis):

        pos_space = torch.linspace(-1, 1, 1001)
        xyz = torch.zeros((pos_space.size(0), 3))
        if axis == "diag":
            xyz[:, 0] = pos_space
            xyz[:, 1] = pos_space
        else:
            xyz[:, axis] = pos_space

        em = emitter.factory(xyz=xyz, xy_unit="px")
        em.frame_ix = torch.arange(pos_space.size(0)).type(em.id.dtype)

        tar_outs = targ.forward(em, None, 0, em.frame_ix.max().item())

        assert (
            tar_outs[:, 0, 0, 0] == (pos_space >= -0.375) * (pos_space < 0.375)
        ).all(), "Central Pixel wrong."

        if axis == 0:
            assert (
                tar_outs[:, 5, 0, 0] == (pos_space >= 0.125) * (pos_space < 0.875)
            ).all()
        elif axis == 1:
            assert (
                tar_outs[:, 10, 0, 0] == (pos_space >= 0.125) * (pos_space < 0.875)
            ).all()
        elif axis == "diag":
            assert (
                tar_outs[:, 15, 0, 0] == (pos_space >= 0.125) * (pos_space < 0.875)
            ).all()


def _mock_tar_emitter_factory():
    """
    Produces a mock target generator that has the apropriate signature and outputs 
    random frames of batch dim that equals the emitters frame span.
    """
    class _MockTargetGenerator:
        @staticmethod
        def forward(em, bg, ix_low, ix_high):
            n_frames = em.frame_ix.max() - em.frame_ix.min() + 1
            return torch.rand(n_frames, 32, 32)
        
    return _MockTargetGenerator()


def test_tar_chain():
    class _MockRescaler:
        @staticmethod
        def forward(x: torch.Tensor):
            return x / x.max()

    tar = target_generator.TargetGeneratorChain(
        [_mock_tar_emitter_factory(), _MockRescaler()]
    )

    out = tar.forward(emitter.factory(frame_ix=[-5, 5]), None)

    assert out.max() == 1.


def test_tar_fork():
    tar = target_generator.TargetGeneratorFork(
        [_mock_tar_emitter_factory(), _mock_tar_emitter_factory()],
    )
    
    out = tar.forward(emitter.factory(frame_ix=[-5, 5]))
    assert len(out) == 2
    assert out[0].size() == torch.Size([11, 32, 32])
    assert out[1].size() == torch.Size([11, 32, 32])


def test_tar_merge():
    tar = target_generator.TargetGeneratorMerger(fn=lambda x, y: torch.cat([x, y]))
    out = tar.forward(torch.rand(5, 32, 32), torch.rand(5, 32, 32))

    assert out.size() == torch.Size([10, 32, 32])


def test_paramlist_tar():
    tar = target_generator.ParameterListTarget(
        n_max=100,
        xextent=(-0.5, 63.5),
        yextent=(-0.5, 63.5),
        xy_unit="px",
        ix_low=0,
        ix_high=3,
    )

    em = emitter.EmitterSet(
        xyz=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
        phot=[3.0, 2.0],
        frame_ix=[0, 2],
        xy_unit="px",
    )

    tar, mask, bg = tar.forward(em)

    assert tar.size() == torch.Size([3, 100, 4])
    assert mask.size() == torch.Size([3, 100])
    assert mask.dtype == torch.bool
    assert mask.sum() == len(em)

    # check the emitters manually
    np.testing.assert_array_equal(tar[0, 0, 0], em[0].phot)
    np.testing.assert_array_equal(tar[0, 0, 1:], em[0].xyz.squeeze())
    np.testing.assert_array_equal(tar[2, 0, 0], em[1].phot)
    np.testing.assert_array_equal(tar[2, 0, 1:], em[1].xyz.squeeze())

    # check that everything but the filled out emitters are nan
    assert torch.isnan(tar[0, 1:]).all()
    assert torch.isnan(tar[1]).all()
    assert torch.isnan(tar[2, 1:]).all()
