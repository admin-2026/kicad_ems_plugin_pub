"""The user's saved entries: the file under them and the merged pickers.

One store and one catalog serve every kind, so these cover the shared machinery
once over the three kinds the core itself has -- metals, substrates and solder
masks -- and then check that each says the right things about itself: what its
fields are, what makes one valid, and which names it must refuse. A kind the
*product* adds is held to the same contract beside its own code (the antenna's
design target, tests/test_applications.py). Pure -- no KiCad, no wx.

    python3 tests/test_userlib.py
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_package import PRODUCT, load, run_module_tests  # noqa: E402

store = load("emkit.userlib.store")
mats_catalog = load("emkit.materials.catalog")
Materials = load("emkit.materials.db").Materials

KINDS = (
    mats_catalog.MetalCatalog,
    mats_catalog.SubstrateCatalog,
    mats_catalog.MaskCatalog,
)


def _catalog(cls, directory):
    """One kind's catalog over a temporary file."""
    return cls(store.UserStore(cls.FILENAME, directory))


def _records(cls, directory):
    """What that kind's file holds, straight off the disk."""
    return json.loads((pathlib.Path(directory) / cls.FILENAME).read_text())


def _saved_mask(directory, name="House mask", eps=3.5, tan_d=0.025):
    cat = _catalog(mats_catalog.MaskCatalog, directory)
    cat.save(name, eps=eps, tan_d=tan_d)
    return cat


def _saved_metal(directory, name="Thick copper", sigma=5.9e7):
    cat = _catalog(mats_catalog.MetalCatalog, directory)
    cat.save(name, sigma=sigma)
    return cat


def _saved_substrate(directory, name="House laminate", eps=3.9, tan_d=0.017):
    cat = _catalog(mats_catalog.SubstrateCatalog, directory)
    cat.save(name, eps=eps, tan_d=tan_d)
    return cat


# --------------------------------------------------------------------------- #
# The file
# --------------------------------------------------------------------------- #
def test_each_kind_keeps_its_own_file():
    with tempfile.TemporaryDirectory() as td:
        _saved_mask(td)
        _saved_metal(td)
        _saved_substrate(td)
        names = sorted(p.name for p in pathlib.Path(td).iterdir())
        assert names == ["masks.json", "metals.json", "substrates.json"]
        # A coating is not offered as the laminate under it, and vice versa --
        # the mask kind holds a substrate's two constants and is still its own.
        assert _catalog(mats_catalog.MaskCatalog, td).saved_names() == ["House mask"]
        assert _catalog(mats_catalog.MetalCatalog, td).saved_names() == ["Thick copper"]


def test_the_file_holds_the_typed_numbers():
    with tempfile.TemporaryDirectory() as td:
        _saved_substrate(td)
        _saved_metal(td)
        assert _records(mats_catalog.SubstrateCatalog, td) == [
            {"name": "House laminate", "eps": 3.9, "tan_d": 0.017}
        ]
        assert _records(mats_catalog.MetalCatalog, td) == [
            {"name": "Thick copper", "sigma": 5.9e7}
        ]


def test_a_saved_entry_survives_the_round_trip():
    with tempfile.TemporaryDirectory() as td:
        _saved_metal(td)
        _saved_substrate(td)
        # Fresh readers: nothing is cached, so another page sees the same.
        metal = _catalog(mats_catalog.MetalCatalog, td).get("Thick copper")
        assert metal.sigma == 5.9e7
        sub = _catalog(mats_catalog.SubstrateCatalog, td).get("House laminate")
        assert sub.eps == 3.9 and sub.tan_d == 0.017


def test_saving_the_same_name_replaces_it_in_place():
    with tempfile.TemporaryDirectory() as td:
        cat = _saved_metal(td)
        cat.save("Other", sigma=1e7)
        cat.save("Thick copper", sigma=6.0e7)
        assert cat.saved_names() == ["Thick copper", "Other"]  # order kept
        assert cat.get("Thick copper").sigma == 6.0e7


def test_delete_forgets_one_and_says_so():
    with tempfile.TemporaryDirectory() as td:
        cat = _saved_metal(td)
        assert cat.delete("Thick copper") is True
        assert cat.delete("Thick copper") is False
        assert cat.saved_names() == []


def test_a_missing_or_broken_file_costs_the_picker_nothing():
    with tempfile.TemporaryDirectory() as td:
        for cls in KINDS:
            cat = _catalog(cls, td)
            assert cat.saved() == []
            assert cat.choices() == list(cat.builtin_names()) + [cat.CUSTOM]
            path = pathlib.Path(td) / cls.FILENAME
            for text in ("{not json", "{}", "[]", '[{"name": ""}, 7]'):
                path.write_text(text, encoding="utf-8")
                assert cat.saved() == [], (cls.__name__, text)


def test_a_record_its_own_kind_refuses_is_skipped():
    # The same rule that refuses a save drops a record somebody hand-edited
    # into nonsense: a picker entry that can't say what it is would be worse
    # than one fewer.
    with tempfile.TemporaryDirectory() as td:
        broken = {
            mats_catalog.MetalCatalog: {"name": "No sigma", "sigma": -1},
            mats_catalog.SubstrateCatalog: {"name": "Air-ish", "eps": 0.5, "tan_d": 0},
            mats_catalog.MaskCatalog: {"name": "No tangent", "eps": 3.5},
        }
        for cls, record in broken.items():
            path = pathlib.Path(td) / cls.FILENAME
            path.write_text(json.dumps([record]), encoding="utf-8")
            assert _catalog(cls, td).saved() == [], cls.__name__


def test_the_default_files_live_in_the_users_config_dir():
    # Not beside a board: a saved entry is the user's, offered on every project
    # (settings keeps the per-project half of the form).
    for cls in KINDS:
        path = cls().store.path
        assert path.name == cls.FILENAME
        assert path.parent.name == store.DIR_NAME
        assert path.parent.parent == store.config_home()


def test_the_directory_is_this_products_own():
    # It used to be one product's name spelled in the shared core, which meant
    # a second plugin built out of the same core kept its user's saved entries
    # in the first one's folder. It is the manifest's now, and the manifest is
    # the only place a product names itself.
    assert store.DIR_NAME == PRODUCT.CONFIG_DIR


# --------------------------------------------------------------------------- #
# The merged catalogs
# --------------------------------------------------------------------------- #
def test_choices_are_builtins_then_saved_then_custom():
    with tempfile.TemporaryDirectory() as td:
        for cat, saved in (
            (_saved_metal(td), "Thick copper"),
            (_saved_substrate(td), "House laminate"),
            (_saved_mask(td), "House mask"),
        ):
            builtins = list(cat.builtin_names())
            assert cat.choices() == builtins + [saved, cat.CUSTOM]


def test_a_saved_entry_is_picked_like_a_builtin():
    with tempfile.TemporaryDirectory() as td:
        metals = _saved_metal(td)
        assert metals.get("Thick copper").sigma == 5.9e7
        assert metals.get("Copper").sigma == 5.8e7
        assert metals.get(Materials.CUSTOM) is None  # the fields are the material
        assert metals.get("Unobtainium") is None  # ... and never copper by default
        assert metals.is_user("Thick copper") and not metals.is_user("Copper")


def test_the_board_substrate_sentinel_still_means_the_board():
    with tempfile.TemporaryDirectory() as td:
        subs = _saved_substrate(td)
        assert subs.choices()[0] == Materials.BOARD_SUBSTRATE
        assert subs.get(Materials.BOARD_SUBSTRATE) is None  # keep the board's eps
        assert not subs.is_user(Materials.BOARD_SUBSTRATE)


def test_no_saved_entry_can_shadow_a_builtin_or_a_sentinel():
    with tempfile.TemporaryDirectory() as td:
        taken = {
            mats_catalog.MetalCatalog: ("Copper", {"sigma": 5.8e7}),
            mats_catalog.MaskCatalog: ("LPI solder mask", {"eps": 3.5, "tan_d": 0.02}),
            # The board-default sentinel is in the substrate's built-in list,
            # so it is refused by the same rule.
            mats_catalog.SubstrateCatalog: (
                Materials.BOARD_SUBSTRATE,
                {"eps": 4.4, "tan_d": 0.02},
            ),
        }
        for cls, (name, values) in taken.items():
            cat = _catalog(cls, td)
            for taken_name in (name, cat.CUSTOM):
                try:
                    cat.save(taken_name, **values)
                    assert False, f"expected ValueError for {taken_name}"
                except ValueError as exc:
                    assert "built-in" in str(exc)


def test_every_kind_needs_a_name():
    with tempfile.TemporaryDirectory() as td:
        for cls in KINDS:
            cat = _catalog(cls, td)
            for blank in ("", "   ", None):
                try:
                    cat.save(blank)
                    assert False, f"expected ValueError for {cls.__name__}"
                except ValueError as exc:
                    assert "name" in str(exc)


def test_the_name_is_saved_stripped():
    with tempfile.TemporaryDirectory() as td:
        cat = _catalog(mats_catalog.MetalCatalog, td)
        assert cat.save("  Padded  ", sigma=1e7).name == "Padded"
        assert cat.is_user("Padded")


def test_each_kind_says_what_its_numbers_must_be():
    # The message is what the dialog shows, so it says what to type.
    with tempfile.TemporaryDirectory() as td:
        cases = (
            (mats_catalog.MetalCatalog, {"sigma": None}, "conductivity"),
            (mats_catalog.MetalCatalog, {"sigma": -1}, "conductivity"),
            (mats_catalog.SubstrateCatalog, {"eps": 0.5, "tan_d": 0.02}, "εr"),
            (mats_catalog.SubstrateCatalog, {"eps": 4.4, "tan_d": -1}, "loss tangent"),
        )
        for cls, values, wanted in cases:
            cat = _catalog(cls, td)
            try:
                cat.save("Nope", **values)
                assert False, f"expected ValueError for {cls.__name__} {values}"
            except ValueError as exc:
                assert wanted in str(exc), (cls.__name__, str(exc))
            assert cat.saved_names() == []


def test_an_entry_says_what_it_is_in_one_line():
    # What the log says a saved entry is, and what a section shows under its
    # picker once one has been chosen.
    with tempfile.TemporaryDirectory() as td:
        assert _saved_metal(td).get("Thick copper").spec_line == "σ 5.9e+07 S/m"
        sub = _saved_substrate(td).get("House laminate").spec_line
        assert sub == "εr 3.9 · tanδ 0.017"


if __name__ == "__main__":
    run_module_tests(globals())
