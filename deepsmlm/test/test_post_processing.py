import pytest
import torch

from deepsmlm.generic import emitter, test_utils
from deepsmlm.neuralfitter import post_processing


class TestPostProcessingAbstract:

    @pytest.fixture(params=["batch-set", "frame-set"], scope="function")
    def post(self, request):
        class PostProcessingMock(post_processing.PostProcessing):
            def forward(self):
                return emitter.EmptyEmitterSet()

        return PostProcessingMock(xy_unit=None, px_size=None, return_format=request.param)

    @pytest.mark.parametrize("return_format", [None, 'batch_set', 'frame_set', 'emitters'])
    def test_sanity(self, post, return_format):
        """
        Tests the sanity checks

        """
        with pytest.raises(ValueError):
            post.return_format = return_format
            post.sanity_check()

    def test_filter(self, post):

        assert not post.skip_if(torch.rand((1, 3, 32, 32)))


class TestNoPostProcessing(TestPostProcessingAbstract):

    @pytest.fixture()
    def post(self):
        return post_processing.NoPostProcessing()

    def test_forward(self, post):

        out = post.forward(torch.rand((256, 2, 64, 64)))
        assert isinstance(out, emitter.EmptyEmitterSet)


class TestLookUpPostProcessing(TestPostProcessingAbstract):

    @pytest.fixture()
    def post(self):
        return post_processing.LookUpPostProcessing(raw_th=0.1, xy_unit='px')

    def test_filter(self, post):

        """Setup"""
        detection = torch.tensor([[0.1, 0.0], [0.6, 0.05]]).unsqueeze(0)

        """Run"""
        active_px = post._filter(detection)

        """Assertions"""
        assert (active_px == torch.tensor([[1, 0], [1, 0]]).unsqueeze(0).bool()).all()

        return active_px

    def test_lookup(self, post):

        """Setup"""
        active_px = self.test_filter(post)  # get the return value of the previous test

        features = torch.tensor([[1., 2.], [3., 4.]]).unsqueeze(0).unsqueeze(0).repeat(1, 5, 1, 1)
        features = features * torch.tensor([1., 2., 3., 4., 5.]).unsqueeze(0).unsqueeze(-1).unsqueeze(-1)

        """Run"""
        batch_ix, features = post._lookup_features(features, active_px)

        """Assertions"""
        assert isinstance(batch_ix, torch.LongTensor), "Batch ix should be integer type."
        assert (batch_ix == 0).all()
        assert batch_ix.size()[0] == features.size()[1]

        # This is hard coded designed for the very specific test case
        assert ((features / (torch.arange(5).unsqueeze(1).float() + 1)).unique() == torch.tensor([1., 3.])).all()

    def test_forward(self, post):

        """Setup"""
        detection = torch.tensor([[0.1, 0.0], [0.6, 0.05]]).unsqueeze(0).unsqueeze(0)
        features = torch.tensor([[1., 2.], [3., 4.]]).unsqueeze(0).unsqueeze(0).repeat(1, 5, 1, 1)
        features = features * torch.tensor([1., 2., 3., 4., 5.]).unsqueeze(0).unsqueeze(-1).unsqueeze(-1)

        pseudo_net_ouput = torch.cat((detection, features), 1)

        """Run"""
        emitter_out = post.forward(pseudo_net_ouput)

        """Assert"""
        assert isinstance(emitter_out, emitter.EmitterSet), "Output should be an emitter."
        assert (emitter_out.frame_ix == 0).all()
        assert (emitter_out.phot.unique() == torch.tensor([1., 3.])).all()


class TestConsistentPostProcessing(TestPostProcessingAbstract):

    @pytest.fixture()
    def post(self):
        return post_processing.ConsistencyPostprocessing(raw_th=0.1, em_th=0.5, xy_unit='px', img_shape=(32, 32),
                                                         ax_th=None, lat_th=0.5, match_dims=2,
                                                         return_format='batch-set')

    @pytest.mark.parametrize("return_format", [None, 'batch_set', 'frame_set', 'emitters'])
    def test_excpt(self, post, return_format):
        """
        Tests the sanity checks and forward expected exceptions

        """
        with pytest.raises(ValueError):
            post.__init__(raw_th=0.1, em_th=0.6, xy_unit='px', img_shape=(32, 32), lat_th=0.,
                          return_format=return_format)

        with pytest.raises(ValueError):
            post.forward(torch.rand((1, 2, 32, 32)))

        with pytest.raises(ValueError):
            post.forward(torch.rand((1, 7, 32, 32)))

    @pytest.mark.xfail(condition=not torch.cuda.is_available(), reason="CUDA not available on this machine.")
    def test_forward_cuda(self, post):
        p = torch.zeros((2, 1, 32, 32)).cuda()
        out = torch.zeros((2, 5, 32, 32)).cuda()
        p[1, 0, 2, 4] = 0.6
        p[1, 0, 2, 6] = 0.6
        p[0, 0, 0, 0] = 0.3
        p[0, 0, 0, 1] = 0.4

        out[0, 2, 0, 0] = 0.3
        out[0, 2, 0, 1] = 0.5
        out[1, 2, 2, 4] = 1.
        out[1, 2, 2, 6] = 1.2

        _ = post.forward(torch.cat((p, out), 1))

    def test_multi_worker(self, post):

        """Setup"""
        p = torch.zeros((2, 1, 32, 32))
        out = torch.zeros((2, 5, 32, 32))
        p[1, 0, 2, 4] = 0.6
        p[1, 0, 2, 6] = 0.6
        p[0, 0, 0, 0] = 0.3
        p[0, 0, 0, 1] = 0.4

        out[0, 2, 0, 0] = 0.3
        out[0, 2, 0, 1] = 0.5
        out[1, 2, 2, 4] = 1.
        out[1, 2, 2, 6] = 1.2

        out[:, 4] = torch.rand_like(out[:, 4])

        """Run"""
        post.num_workers = 0
        em0 = post.forward(torch.cat((p, out), 1))

        post.num_workers = 4
        em1 = post.forward(torch.cat((p, out), 1))

        """Assert (equal outcome)"""
        for i in range(len(em0)):
            assert em0[i] == em1[i]

    def test_easy_case(self, post):
        """
        Easy case, i.e. isolated active pixels.

        Args:
            post: fixture

        """

        """Setup"""
        p = torch.zeros((2, 1, 32, 32))
        out = torch.zeros((2, 5, 32, 32))
        p[0, 0, 0, 0] = 0.3
        p[0, 0, 0, 2] = 0.4
        p[1, 0, 2, 4] = 0.6
        p[1, 0, 2, 6] = 0.6

        out[0, 2, 0, 0] = 0.3
        out[0, 2, 0, 2] = 0.5
        out[1, 2, 2, 4] = 1.
        out[1, 2, 2, 6] = 1.2

        """Run"""
        p_out, feat_out = post._forward_raw_impl(p, out)
        em_out = post.forward(torch.cat((p, out), 1))

        """Assertions"""
        assert test_utils.tens_almeq(p, p_out)
        assert test_utils.tens_almeq(out, feat_out)

        assert isinstance(em_out, emitter.EmitterSet)
        assert len(em_out) == 2
        assert (em_out.prob >= post.em_th).all()

    def test_hard_cases(self, post):
        """Non-isolated emitters."""

        """Setup"""
        p = torch.zeros((3, 1, 32, 32))
        out = torch.zeros((3, 5, 32, 32))
        p[0, 0, 0, 0] = 0.7  # isolated
        p[0, 0, 0, 2] = 0.7  # isolated
        p[1, 0, 2, 4] = 0.6  # should be merged
        p[1, 0, 2, 5] = 0.6  # should be merged
        p[2, 0, 4, 4] = 0.7  # should not be merged
        p[2, 0, 4, 5] = 0.7  # should not be merged

        out[1, 1, 2, 4] = 20.  # should be merged
        out[1, 1, 2, 5] = 20.2  # %
        out[2, 2, 4, 4] = 49.  # should not be merged
        out[2, 2, 4, 5] = 49.51  # %

        """Run"""
        em_out = post.forward(torch.cat((p, out), 1))

        """Assertions"""
        # First frame
        assert len(em_out.get_subset_frame(0, 0)) == 2
        assert (em_out.get_subset_frame(0, 0).prob == 0.7).all()

        # Second frame
        assert len(em_out.get_subset_frame(1, 1)) == 1
        assert (em_out.get_subset_frame(1, 1).prob.item() > 0.6)

        # Third frame
        assert len(em_out.get_subset_frame(2, 2)) == 2
        assert (em_out.get_subset_frame(2, 2).prob == 0.7).all()

    @pytest.mark.parametrize("x,expct", [(torch.ones((2, 6, 32, 32)), True),
                                         (torch.zeros((2, 6, 32, 32)), False),
                                         (torch.tensor([[0.5, 0., 0.], [0., 0., 0.]]).unsqueeze(0).unsqueeze(0), False)])
    def test_filter(self, post, x, expct):

        post.skip_th = 0.2
        assert post.skip_if(x) is expct
