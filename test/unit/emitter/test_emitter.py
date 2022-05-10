import numpy as np
import pytest
import torch
from hypothesis import given, settings, strategies as st
from pathlib import Path
from unittest import mock

from decode.generic import test_utils
from decode.emitter import emitter
from decode.emitter.emitter import (
    LooseEmitterSet,
    EmitterSet,
    CoordinateOnlyEmitter,
    EmitterData,
)


def test_emitter_data():
    EmitterData(
        xyz=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]],
        phot=[1.0, 2.0, 3.0],
        frame_ix=[1, 2, 3],
    )


@pytest.fixture()
def em2d():
    """Effectively 2D EmitterSet"""

    return EmitterSet(
        xyz=torch.rand((25, 2)),
        phot=torch.rand(25),
        frame_ix=torch.zeros(25, dtype=torch.long),
    )


@pytest.fixture()
def em3d():
    """Most basic (i.e. all necessary fields) 3D EmitterSet"""

    frames = torch.arange(25, dtype=torch.long)
    frames[[0, 1, 2]] = 1
    return EmitterSet(xyz=torch.rand((25, 3)), phot=torch.rand(25), frame_ix=frames)


@pytest.fixture
def em3d_full(em3d):
    return EmitterSet(
        xyz=em3d.xyz,
        phot=em3d.phot,
        bg=torch.rand_like(em3d.phot) * 100,
        frame_ix=em3d.frame_ix,
        id=em3d.id,
        xyz_sig=torch.rand_like(em3d.xyz),
        phot_sig=torch.rand_like(em3d.phot) * em3d.phot.sqrt(),
        xyz_cr=torch.rand_like(em3d.xyz) ** 2,
        phot_cr=torch.rand_like(em3d.phot) * em3d.phot.sqrt() * 1.5,
        bg_cr=torch.rand_like(em3d.phot),
        xy_unit="nm",
        px_size=(100.0, 200.0),
    )


class TestEmitterSet:
    @given(
        xyz=st.sampled_from([torch.rand(42, 2), torch.rand(42, 3)]),
        phot=st.sampled_from([torch.rand(42)]),
        frame_ix=st.sampled_from([torch.arange(42)]),
        color=st.sampled_from([None, torch.randint(5, size=(42,))]),
        id=st.sampled_from([None, -torch.arange(42)]),
        prob=st.sampled_from([None, torch.rand(42)]),
        bg=st.sampled_from([None, torch.rand(42)]),
        xyz_cr=st.sampled_from([None, torch.rand(42, 3)]),
        phot_cr=st.sampled_from([None, torch.rand(42, 3)]),
        bg_cr=st.sampled_from([None, torch.rand(42, 3)]),
        xyz_sig=st.sampled_from([None, torch.rand(42, 3)]),
        phot_sig=st.sampled_from([None, torch.rand(42)]),
        bg_sig=st.sampled_from([None, torch.rand(42)]),
        xy_px=st.sampled_from([(None, None), ("px", (120.0, 240.0))]),
    )
    def test_props(
        self,
        xyz,
        phot,
        frame_ix,
        id,
        color,
        prob,
        bg,
        xyz_cr,
        phot_cr,
        bg_cr,
        xyz_sig,
        phot_sig,
        bg_sig,
        xy_px,
    ):

        em = EmitterSet(
            xyz=xyz,
            phot=phot,
            frame_ix=frame_ix,
            id=id,
            color=color,
            prob=prob,
            bg=bg,
            xyz_cr=xyz_cr,
            phot_cr=phot_cr,
            bg_cr=bg_cr,
            xyz_sig=xyz_sig,
            phot_sig=phot_sig,
            bg_sig=bg_sig,
            xy_unit=xy_px[0],
            px_size=xy_px[1],
        )

        # ToDo: Add asserts
        em.xyz
        em.phot
        em.id
        em.frame_ix

        # access nm / px suffix properties
        if em.px_size is not None and em.xy_unit is not None:
            em.xyz_px
            em.xyz_nm
            em.xyz_scr
            em.xyz_scr_px
            em.xyz_scr_nm
            em.xyz_sig_px
            em.xyz_sig_nm
            em.xyz_sig_tot_nm
            em.xyz_sig_weighted_tot_nm

    def test_dim(self, em2d, em3d):

        assert em2d.dim() == 2
        assert em3d.dim() == 3

    def test_xyz_shape(self, em2d, em3d):
        """
        Tests shape and correct data type
        Args:
            em2d: fixture (see above)
            em3d: fixture (see above)

        Returns:

        """

        # 2D input get's converted to 3D with zeros
        assert em2d.xyz.shape[1] == 3
        assert em3d.xyz.shape[1] == 3
        assert em3d.frame_ix.dtype == torch.long

    xyz_conversion_data = [  # xyz_input, # xy_unit, #px-size # expect px, # expect nm
        (torch.empty((0, 3)), None, None, "err", "err"),
        (torch.empty((0, 3)), "px", None, torch.empty((0, 3)), "err"),
        (torch.empty((0, 3)), "nm", None, "err", torch.empty((0, 3))),
        (torch.tensor([[25.0, 25.0, 5.0]]), None, None, "err", "err"),
        (
            torch.tensor([[25.0, 25.0, 5.0]]),
            "px",
            None,
            torch.tensor([[25.0, 25.0, 5.0]]),
            "err",
        ),
        (
            torch.tensor([[25.0, 25.0, 5.0]]),
            "nm",
            None,
            "err",
            torch.tensor([[25.0, 25.0, 5.0]]),
        ),
        (
            torch.tensor([[0.25, 0.25, 5.0]]),
            "px",
            (50.0, 100.0),
            torch.tensor([[0.25, 0.25, 5.0]]),
            torch.tensor([[12.5, 25.0, 5.0]]),
        ),
        (
            torch.tensor([[25.0, 25.0, 5.0]]),
            "nm",
            (50.0, 100.0),
            torch.tensor([[0.5, 0.25, 5.0]]),
            torch.tensor([[25.0, 25.0, 5.0]]),
        ),
    ]

    @pytest.mark.parametrize(
        "xyz_input,xy_unit,px_size,expct_px,expct_nm", xyz_conversion_data
    )
    @pytest.mark.filterwarnings("ignore:UserWarning")
    def test_xyz_conversion(self, xyz_input, xy_unit, px_size, expct_px, expct_nm):

        """Init and expect warning if specified"""
        em = CoordinateOnlyEmitter(xyz_input, xy_unit=xy_unit, px_size=px_size)

        """Test the respective units"""
        if isinstance(expct_px, str) and expct_px == "err":
            with pytest.raises(ValueError):
                _ = em.xyz_px
        else:
            assert test_utils.tens_almeq(em.xyz_px, expct_px)

        if isinstance(expct_nm, str) and expct_nm == "err":
            with pytest.raises(ValueError):
                _ = em.xyz_nm

        else:
            assert test_utils.tens_almeq(em.xyz_nm, expct_nm)

    xyz_cr_conversion_data = [
        # xyz_scr_input, # xy_unit, #px-size # expect_scr_px, # expect scr_nm
        (torch.empty((0, 3)), None, None, "err", "err"),
        (torch.empty((0, 3)), "px", None, torch.empty((0, 3)), "err"),
        (torch.empty((0, 3)), "nm", None, "err", torch.empty((0, 3))),
        (torch.tensor([[25.0, 25.0, 5.0]]), None, None, "err", "err"),
        (
            torch.tensor([[25.0, 25.0, 5.0]]),
            "px",
            None,
            torch.tensor([[25.0, 25.0, 5.0]]),
            "err",
        ),
        (
            torch.tensor([[25.0, 25.0, 5.0]]),
            "nm",
            None,
            "err",
            torch.tensor([[25.0, 25.0, 5.0]]),
        ),
        (
            torch.tensor([[0.25, 0.25, 5.0]]),
            "px",
            (50.0, 100.0),
            torch.tensor([[0.25, 0.25, 5.0]]),
            torch.tensor([[12.5, 25.0, 5.0]]),
        ),
        (
            torch.tensor([[25.0, 25.0, 5.0]]),
            "nm",
            (50.0, 100.0),
            torch.tensor([[0.5, 0.25, 5.0]]),
            torch.tensor([[25.0, 25.0, 5.0]]),
        ),
    ]

    @pytest.mark.parametrize(
        "xyz_scr_input,xy_unit,px_size,expct_px,expct_nm", xyz_cr_conversion_data
    )
    @pytest.mark.filterwarnings("ignore:UserWarning")
    def test_xyz_cr_conversion(
        self, xyz_scr_input, xy_unit, px_size, expct_px, expct_nm
    ):
        """
        Here we test the cramer rao unit conversion. We can reuse the testdata as for the xyz conversion because it does
        not make a difference for the test candidate.

        """

        """Init and expect warning if specified"""
        em = CoordinateOnlyEmitter(
            torch.rand_like(xyz_scr_input), xy_unit=xy_unit, px_size=px_size
        )
        em.xyz_cr = xyz_scr_input**2

        """Test the respective units"""
        if isinstance(expct_px, str) and expct_px == "err":
            with pytest.raises(ValueError):
                _ = em.xyz_cr_px
        else:
            assert test_utils.tens_almeq(em.xyz_scr_px, expct_px)

        if isinstance(expct_nm, str) and expct_nm == "err":
            with pytest.raises(ValueError):
                _ = em.xyz_cr_nm

        else:
            assert test_utils.tens_almeq(em.xyz_scr_nm, expct_nm)

    @pytest.mark.parametrize("attr,power", [("xyz", 1), ("xyz_sig", 1), ("xyz_cr", 2)])
    def test_property_conversion(self, attr, power, em3d_full):
        with mock.patch.object(EmitterSet, "_pxnm_conversion") as conversion:
            getattr(em3d_full, attr + "_nm")

        conversion.assert_called_once_with(
            getattr(em3d_full, attr), in_unit="nm", tar_unit="nm", power=power
        )

    @mock.patch.object(EmitterSet, "cat")
    def test_add(self, mock_add):
        em_0 = emitter.factory(20)
        em_1 = emitter.factory(100)

        _ = em_0 + em_1
        mock_add.assert_called_once_with((em_0, em_1), None, None)

    def test_iadd(self):
        em_0 = emitter.factory(20)
        em_1 = emitter.factory(50)

        em_0 += em_1
        assert len(em_0) == 70

    def test_chunk(self):

        big_em = emitter.factory(100000)

        splits = big_em.chunks(10000)
        re_merged = EmitterSet.cat(splits)

        assert sum([len(e) for e in splits]) == len(big_em)
        assert re_merged == big_em

        # test not evenly splittable number
        em = emitter.factory(7)
        splits = em.chunks(3)

        assert len(splits[0]) == 3
        assert len(splits[1]) == 2
        assert len(splits[-1]) == 2

    @settings(max_examples=100)
    @given(
        frame_ix=st.lists(st.integers(min_value=int(-1e6), max_value=int(1e6))),
        ix_range=st.tuples(
            st.integers(min_value=int(-1e6), max_value=int(1e6)),
            st.integers(min_value=int(-1e6), max_value=int(1e6)),
        ),
    )
    def test_get_subset_frames(self, frame_ix, ix_range):
        xyz = torch.rand((len(frame_ix), 3))
        frame_ix = torch.LongTensor(frame_ix)
        em = EmitterSet(xyz=xyz, phot=torch.ones_like(frame_ix), frame_ix=frame_ix)

        ix_range = sorted(ix_range)
        em_out = em.get_subset_frame(*ix_range)

        if len(em) == 0 or ix_range[0] == ix_range[1]:
            assert len(em_out) == 0

        elif len(em_out) == 0:
            # below lower end or above upper end
            assert set(torch.arange(*ix_range).tolist()).isdisjoint(
                set(em.frame_ix.tolist())
            )

        else:
            assert em_out.frame_ix.min() >= ix_range[0]
            assert em_out.frame_ix.max() < ix_range[1]

    @pytest.mark.parametrize(
        "frame_select,expct",
        [
            (slice(2, 5), {2, 3, 4}),
            (2, {2}),
        ],
    )
    def test_iframe(self, frame_select, expct):
        em = emitter.factory(frame_ix=[0, 1, 2, 3, 4, 5, 6, 7])
        em_out = em.iframe[frame_select]

        assert set(em_out.frame_ix.unique().tolist()) == expct

    @pytest.mark.parametrize("accessor", [slice(2, 5, 2), [1, 2, 3]])
    def test_iframe_notimplemented(self, accessor):
        # at the moment only integer and slicing getitem is supported via iframe.
        # once emitter.iframe[2:5:2] is supported change test accordingly

        em = emitter.factory(20)
        with pytest.raises(NotImplementedError):
            em.iframe[accessor]

    @settings(max_examples=100)
    @given(
        frame_ix=st.lists(st.integers(min_value=int(-1e2), max_value=int(1e2))),
        split_range=st.tuples(
            st.integers(min_value=int(-1e2), max_value=int(1e2)),
            st.integers(min_value=int(-1e2), max_value=int(1e2)),
        ),
    )
    def test_split_in_frames(self, frame_ix, split_range):
        frame_ix = torch.LongTensor(frame_ix)
        split_range = sorted(split_range)

        splits = emitter.factory(frame_ix=frame_ix).split_in_frames(*split_range)

        if split_range[0] == split_range[1]:
            assert len(splits) == 0
            return

        assert len(splits) == split_range[1] - split_range[0], "Incorrect split length."

        # check that frame indices are correct per split
        frame_ix_exp = torch.arange(*split_range)
        for s, f_ix in zip(splits, frame_ix_exp):
            assert (s.frame_ix == f_ix).all(), "Incorrect frame ix."

    def test_cat_emittersets(self):

        sets = [emitter.factory(50), emitter.factory(20)]
        cat_sets = EmitterSet.cat(sets, None, 1)
        assert 70 == len(cat_sets)
        assert 0 == cat_sets.frame_ix[0]
        assert 1 == cat_sets.frame_ix[50]

        sets = [emitter.factory(50), emitter.factory(20)]
        cat_sets = EmitterSet.cat(sets, torch.tensor([5, 50]), None)
        assert 70 == len(cat_sets)
        assert 5 == cat_sets.frame_ix[0]
        assert 50 == cat_sets.frame_ix[50]

        # test correctness of px size and xy unit
        sets = [
            emitter.factory(50, xy_unit="px", px_size=(100.0, 200.0)),
            emitter.factory(20),
        ]
        em = EmitterSet.cat(sets)
        assert em.xy_unit == "px"
        assert (em.px_size == torch.tensor([100.0, 200.0])).all()

    def test_split_cat(self):
        """
        Tests whether split and cat (and sort by ID) returns the same result as the original
        """

        em = emitter.factory(1000)
        em.id = torch.arange(len(em))
        em.frame_ix = torch.randint_like(em.frame_ix, 10000)

        """Run"""
        em_split = em.split_in_frames(0, 9999)
        em_re_merged = EmitterSet.cat(em_split)

        """Assertions"""
        # sort both by id
        ix = torch.argsort(em.id)
        ix_re = torch.argsort(em_re_merged.id)

        assert em[ix] == em_re_merged[ix_re]

    @pytest.mark.parametrize("frac", [0.0, 0.1, 0.5, 0.9, 1.0])
    def test_sigma_filter(self, frac):

        """Setup"""
        em = emitter.factory(10000)
        em.xyz_sig = (torch.randn(len(em), 3) + 5).clamp(0.0)

        """Run"""
        out = em.filter_by_sigma(fraction=frac)

        """Assert"""
        assert len(em) * frac == pytest.approx(len(out))

    def test_hist_detection(self):

        em = emitter.factory(10000)
        em.prob = torch.rand(len(em))
        em.xyz_sig = torch.randn(len(em), 3) * torch.tensor([1.0, 2.0, 3.0]).unsqueeze(
            0
        )

        """Run"""
        out = em.hist_detection()

        """Assert"""
        assert set(out.keys()) == {"prob", "sigma_x", "sigma_y", "sigma_z"}

    def test_sanity_check(self):
        em = emitter.factory(42)
        em.frame_ix = torch.rand(42, 1)  # not sane frame index

        with pytest.raises(ValueError):
            em._sanity_check()

        """Test correct number of el. in EmitterSet."""
        em = emitter.factory(42)
        em.phot = torch.rand(43)  # incorrect number of photons

        with pytest.raises(ValueError):
            em._sanity_check()

    @pytest.mark.parametrize(
        "em",
        [
            emitter.factory(25, extent=64, px_size=(100.0, 125.0)),
            emitter.factory(0, xy_unit="nm", px_size=(100.0, 125.0)),
        ],
    )
    def test_inplace_replace(self, em):
        em_start = emitter.factory(25, xy_unit="px", px_size=None)
        em_start._inplace_replace(em)

        assert em_start == em

    @pytest.mark.parametrize("format", [".pt", ".h5", ".csv"])
    @pytest.mark.filterwarnings("ignore:.*For .csv files, implicit usage of .load()")
    def test_save_load(self, format, tmpdir):

        em = emitter.factory(1000, xy_unit="nm", px_size=(100.0, 100.0))

        p = Path(tmpdir / f"em{format}")
        em.save(p)
        em_load = EmitterSet.load(p)
        assert em == em_load, "Reloaded emitterset is not equivalent to inital one."

    @pytest.mark.parametrize(
        "em_a,em_b,expct",
        [
            # both are the same
            (
                CoordinateOnlyEmitter(torch.tensor([[0.0, 1.0, 2.0]])),
                CoordinateOnlyEmitter(torch.tensor([[0.0, 1.0, 2.0]])),
                True,
            ),
            # different units
            (
                CoordinateOnlyEmitter(torch.tensor([[0.0, 1.0, 2.0]]), xy_unit="px"),
                CoordinateOnlyEmitter(torch.tensor([[0.0, 1.0, 2.0]]), xy_unit="nm"),
                False,
            ),
            # different coordinates
            (
                CoordinateOnlyEmitter(torch.tensor([[0.0, 1.0, 2.0]]), xy_unit="px"),
                CoordinateOnlyEmitter(torch.tensor([[1000.0, 1.1, 2.0]]), xy_unit="px"),
                False,
            ),
        ],
    )
    def test_eq(self, em_a, em_b, expct):
        if expct:
            assert em_a == em_b
        else:
            assert not (em_a == em_b)

    def test_meta(self):

        em = emitter.factory(100, xy_unit="nm", px_size=(100.0, 200.0))
        assert set(em.meta.keys()) == {"xy_unit", "px_size"}

    def test_to_dict(self):

        em = emitter.factory(100, xy_unit="nm", px_size=(100.0, 200.0))

        # check whether doing one round of to_dict and back works
        em_clone = em.clone()
        em_dict = EmitterSet(**em.to_dict())

        assert em_clone == em_dict

    def test_data_used(self):
        em = emitter.factory(42)

        em_data_full = em.data
        em_data_used = em.data_used
        diff = set(em_data_full.keys()) - set(em_data_used.keys())

        assert set(em_data_used.keys()).issubset((em_data_full.keys()))
        for d in diff:
            assert em_data_full[d] is None


def test_empty_emitterset():
    em = emitter.factory(0)
    assert len(em) == 0


def test_factory():
    em = emitter.factory(100, xyz=torch.zeros(100, 3), phot_cr=torch.ones(100))

    assert isinstance(em, EmitterSet)
    assert len(em) == 100
    assert (em.xyz == 0.0).all()
    assert (em.phot_cr == 1).all()


def test_factory_empty():
    em = emitter.factory(0)
    assert len(em) == 0


@pytest.mark.parametrize(
    "attr,val,exp_len",
    [
        ("xyz", torch.rand(42, 3), 42),
        ("phot", torch.rand(43), 43),
        ("frame_ix", torch.randint(1000, size=(44,)), 44),
        ("abcdefg", 42, "raise"),
    ],
)
def test_factory_inferred_length(attr, val, exp_len):
    kwargs = {attr: val}

    if exp_len == "raise":
        with pytest.raises(NotImplementedError):
            emitter.factory(**kwargs)
        return

    em = emitter.factory(**kwargs)
    assert len(em) == exp_len


@pytest.mark.parametrize(
    "attr,len_exp",
    [(None, 17), ("xyz", 42), ("phot", 84), ("frame_ix", 122), ("id", 180)],
)
def test_random_emitterset(attr, len_exp):
    """Test whether random emitterset is constructed from attribute correctly"""
    if attr is None:
        em = emitter.factory(n=len_exp)
    elif attr == "xyz":
        em = emitter.factory(xyz=torch.rand((len_exp, 3)))
    elif attr == "phot":
        em = emitter.factory(phot=torch.rand(len_exp))
    elif attr == "frame_ix":
        em = emitter.factory(frame_ix=torch.randint(0, 1000, size=(len_exp,)))
    elif attr == "id":
        em = emitter.factory(id=torch.randint(0, 10000, size=(len_exp,)))

    assert len(em) == len_exp


class TestLooseEmitterSet:
    def test_sanity(self):
        with pytest.raises(ValueError) as err:  # wrong xyz dimension
            _ = LooseEmitterSet(
                xyz=torch.rand((20, 1)),
                intensity=torch.ones(20),
                ontime=torch.ones(20),
                t0=torch.rand(20),
                id=None,
                xy_unit="px",
                px_size=None,
            )
        assert str(err.value) == "Wrong xyz dimension."

        with pytest.raises(ValueError) as err:  # non unique IDs
            _ = LooseEmitterSet(
                xyz=torch.rand((20, 3)),
                intensity=torch.ones(20),
                ontime=torch.ones(20),
                t0=torch.rand(20),
                id=torch.ones(20),
                xy_unit="px",
                px_size=None,
            )
        assert str(err.value) == "IDs are not unique."

        with pytest.raises(ValueError) as err:  # negative intensity
            _ = LooseEmitterSet(
                xyz=torch.rand((20, 3)),
                intensity=-torch.ones(20),
                ontime=torch.ones(20),
                t0=torch.rand(20),
                id=None,
                xy_unit="px",
                px_size=None,
            )
        assert str(err.value) == "Negative intensity values encountered."

        with pytest.raises(ValueError) as err:  # negative intensity
            _ = LooseEmitterSet(
                xyz=torch.rand((20, 3)),
                intensity=torch.ones(20),
                ontime=-torch.ones(20),
                t0=torch.rand(20),
                id=None,
                xy_unit="px",
                px_size=None,
            )
        assert str(err.value) == "Negative ontime encountered."

    def test_frame_distribution(self):
        em = LooseEmitterSet(
            xyz=torch.Tensor([[1.0, 2.0, 3.0], [7.0, 8.0, 9.0]]),
            intensity=torch.Tensor([1.0, 2.0]),
            t0=torch.Tensor([-0.5, 3.2]),
            ontime=torch.Tensor([0.4, 2.0]),
            id=torch.tensor([0, 1]),
            sanity_check=True,
            xy_unit="px",
            px_size=None,
        )

        """Distribute"""
        xyz, phot, frame_ix, id = em._distribute_framewise()
        # sort by id then by frame_ix
        ix = np.lexsort((id, frame_ix))
        id = id[ix]
        xyz = xyz[ix, :]
        phot = phot[ix]
        frame_ix = frame_ix[ix]

        """Assert"""
        assert (xyz[0] == torch.Tensor([1.0, 2.0, 3.0])).all()
        assert id[0] == 0
        assert frame_ix[0] == -1
        assert phot[0] == 0.4 * 1

        assert (xyz[1:4] == torch.Tensor([7.0, 8.0, 9.0])).all()
        assert (id[1:4] == 1).all()
        assert (frame_ix[1:4] == torch.Tensor([3, 4, 5])).all()
        assert test_utils.tens_almeq(
            phot[1:4], torch.tensor([0.8 * 2, 2, 0.2 * 2]), 1e-6
        )

    @pytest.fixture()
    def dummy_set(self):
        num_emitters = 10000
        t0_max = 5000
        em = LooseEmitterSet(
            torch.rand((num_emitters, 3)),
            torch.ones(num_emitters) * 10000,
            torch.rand(num_emitters) * 3,
            torch.rand(num_emitters) * t0_max,
            None,
            xy_unit="px",
            px_size=None,
        )

        return em

    def test_distribution(self):
        loose_em = LooseEmitterSet(
            torch.zeros((2, 3)),
            torch.tensor([1000.0, 10]),
            torch.tensor([1.0, 5]),
            torch.tensor([-0.2, 0.9]),
            xy_unit="px",
            px_size=None,
        )

        loose_em.return_emitterset()