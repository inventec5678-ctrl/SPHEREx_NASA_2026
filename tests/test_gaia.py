"""sxlib/gaia.py without the network: ESA's CSV, MAST's VOTable and MAST's catalog JSON are mocked.
pytest tests/test_gaia.py"""
import json
import math

import pytest

from sxlib import gaia

ESA_CSV = """source_id,ra,dec,phot_g_mean_mag,phot_variable_flag,astrometric_primary_flag,radial_velocity
4472832130942575872,269.44850252543836,4.739420051112412,8.1939745,NOT_AVAILABLE,true,-110.46822
4472832822422325632,269.45,4.74,16.229185,VARIABLE,false,
"""

MAST_VOT = """<?xml version="1.0" encoding="utf-8"?>
<VOTABLE version="1.4" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
<RESOURCE type="results">
<INFO name="QUERY_STATUS" value="OK"/>
<TABLE>
<FIELD name="source_id" datatype="long"/>
<FIELD name="ra" datatype="double"/>
<FIELD name="dec" datatype="double"/>
<FIELD name="phot_g_mean_mag" datatype="float"/>
<FIELD name="phot_variable_flag" datatype="char" arraysize="*"/>
<FIELD name="astrometric_primary_flag" datatype="bit"/>
<FIELD name="radial_velocity" datatype="float"/>
<DATA><TABLEDATA>
<TR><TD>4472832130942575872</TD><TD>269.44850252543836</TD><TD>4.739420051112412</TD><TD>8.193974494934082</TD><TD>NOT_AVAILABLE   </TD><TD>1</TD><TD>-110.46822357177734</TD></TR>
<TR><TD>4472832822422325632</TD><TD>269.45</TD><TD>4.74</TD><TD>16.229185104370117</TD><TD>VARIABLE   </TD><TD>0</TD><TD></TD></TR>
</TABLEDATA></DATA>
</TABLE>
</RESOURCE>
</VOTABLE>"""

MAST_ERR = """<?xml version="1.0" encoding="UTF-8"?>
<VOTABLE version="1.4" xmlns="http://www.ivoa.net/xml/VOTable/v1.3"><RESOURCE type="results">
<INFO name="QUERY_STATUS" value="ERROR">Exception translating ADQL: unknown table</INFO></RESOURCE></VOTABLE>"""

MAST_CAT = {"status": "COMPLETE", "msg": "", "paging": {"page": 1, "pageSize": 50000, "pagesFiltered": 1, "rows": 3},
            "fields": [{"name": "source_id", "type": "string"}, {"name": "ra", "type": "float"}, {"name": "dec", "type": "float"},
                       {"name": "phot_g_mean_mag", "type": "float"}, {"name": "astrometric_primary_flag", "type": "boolean"},
                       {"name": "distance", "type": "float"}],
            "data": [{"source_id": 3, "ra": 10.0, "dec": 1.0, "phot_g_mean_mag": 19.5, "astrometric_primary_flag": False, "distance": 0.1},
                     {"source_id": 1, "ra": 10.001, "dec": 1.0, "phot_g_mean_mag": 12.25, "astrometric_primary_flag": True, "distance": 0.05},
                     {"source_id": 2, "ra": 10.0, "dec": 1.001, "phot_g_mean_mag": 8.19397449, "astrometric_primary_flag": False, "distance": 0.06}]}


class Resp:
    def __init__(self, text="", status=200, js=None):
        self.text, self.status_code, self._js = text, status, js
        self.content = text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._js


class FakeRequests:
    """Answers per service: a Resp, or an exception to raise. Records every call."""

    def __init__(self, esa=None, mast=None, cat=None):
        self.ans = {"esa": esa, "mast": mast, "cat": cat}
        self.calls = []

    def _reply(self, key):
        a = self.ans[key]
        if a is None or isinstance(a, Exception):
            raise a or ConnectionError(f"{key} down")
        return a

    def get(self, url, params=None, **kw):
        assert url == gaia.ESA_TAP
        self.calls.append(("esa", params["QUERY"]))
        return self._reply("esa")

    def post(self, url, data=None, **kw):
        if url == gaia.MAST_TAP:
            self.calls.append(("mast", data["QUERY"]))
            return self._reply("mast")
        assert url == gaia.MAST_API
        self.calls.append(("cat", json.loads(data["request"])))
        return self._reply("cat")


@pytest.fixture
def fake(monkeypatch):
    def make(**kw):
        f = FakeRequests(**kw)
        monkeypatch.setattr(gaia, "_requests", lambda: f)
        return f
    return make


Q = "SELECT TOP 5 source_id,ra,dec FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT(ra,dec),CIRCLE(269.4,4.7,0.1))"


def test_esa_first(fake):
    f = fake(esa=Resp(ESA_CSV), mast=Resp(MAST_VOT))
    rows = gaia.query(Q)
    assert gaia.last["service"] == "esa" and [c[0] for c in f.calls] == ["esa"]
    assert rows[0] == {"source_id": "4472832130942575872", "ra": "269.44850252543836", "dec": "4.739420051112412",
                       "phot_g_mean_mag": "8.1939745", "phot_variable_flag": "NOT_AVAILABLE", "astrometric_primary_flag": "true",
                       "radial_velocity": "-110.46822"}
    assert rows[1]["radial_velocity"] == ""


@pytest.mark.parametrize("esa", [ConnectionError("refused"), Resp("<html>maintenance</html>"), Resp("", status=503)])
def test_mast_fallback_reads_like_esa(fake, esa):
    f = fake(esa=esa, mast=Resp(MAST_VOT))
    rows = gaia.query(Q)
    assert gaia.last["service"] == "mast"
    assert f.calls[1] == ("mast", Q.replace("gaiadr3.gaia_source", "dbo.gaia_source"))
    # the same strings ESA's CSV has: float32 precision, trimmed text, true/false, '' for null
    assert rows == gaia._parse_csv(ESA_CSV)


def test_mast_adql_rewrites_every_table():
    q = "SELECT a.x FROM gaiadr3.gaia_source AS a JOIN gaiadr3.vari_summary AS s ON s.source_id=a.source_id"
    assert gaia.mast_adql(q) == "SELECT a.x FROM dbo.gaia_source AS a JOIN dbo.vari_summary AS s ON s.source_id=a.source_id"


def test_all_fail_raises(fake):
    fake(esa=ConnectionError("a"), mast=Resp(MAST_ERR))
    with pytest.raises(gaia.GaiaError) as e:
        gaia.query(Q)
    assert "esa:" in str(e.value) and "unknown table" in str(e.value)


def test_cone_query_text_is_the_old_one(fake):
    """The callers' ADQL is unchanged, so ESA returns exactly what it returned before."""
    f = fake(esa=Resp("ra,dec\n1,2\n"))
    gaia.cone(269.4, 4.7, 0.225, ["ra", "dec", "pmra", "pmdec", "phot_g_mean_mag"], max_g=19, top=4000)
    assert f.calls[0][1] == ("SELECT TOP 4000 ra,dec,pmra,pmdec,phot_g_mean_mag FROM gaiadr3.gaia_source WHERE "
                             "1=CONTAINS(POINT(ra,dec),CIRCLE(269.4,4.7,0.225)) AND phot_g_mean_mag<19 ORDER BY phot_g_mean_mag")


def test_cone_falls_back_to_mast_catalog(fake):
    f = fake(esa=ConnectionError("down"), mast=ConnectionError("down"), cat=Resp(js=MAST_CAT))
    rows = gaia.cone(10.0, 1.0, 0.01, ["source_id", "phot_g_mean_mag", "astrometric_primary_flag"], max_g=19, top=5)
    assert gaia.last["service"] == "mast-catalog"
    assert f.calls[2][1]["service"] == "Mast.Catalogs.GaiaDR3.Cone" and f.calls[2][1]["params"] == {"ra": 10.0, "dec": 1.0, "radius": 0.01}
    # G < 19 kept, sorted by G, float32 formatting, booleans as ESA writes them, only the asked columns
    assert rows == [{"source_id": "2", "phot_g_mean_mag": "8.1939745", "astrometric_primary_flag": "false"},
                    {"source_id": "1", "phot_g_mean_mag": "12.25", "astrometric_primary_flag": "true"}]


def _row(sid, ra, dec, g, pmra=0.0, pmdec=0.0, plx=1.0, var="NOT_AVAILABLE"):
    r = {c: "" for c in gaia.STAR_COLS}
    r.update(source_id=str(sid), ra=repr(ra), dec=repr(dec), phot_g_mean_mag=str(g), pmra=str(pmra), pmdec=str(pmdec),
             pm=str(math.hypot(pmra, pmdec)), parallax=str(plx), parallax_error="0.05", bp_rp="1.5", ruwe="1.0", phot_variable_flag=var)
    return r


def test_star_follows_proper_motion_and_picks_the_bright_one(monkeypatch):
    # a click at (100, 10) in 2026.0: a fast star that was 52" away in 2016 is there now; a faint star sits closer
    pmdec = 5200.0                                               # mas/yr: 52" in 10 years
    rows = [_row(1, 100.0, 10.0 - 52.0 / 3600, 9.0, pmdec=pmdec, plx=500.0),
            _row(2, 100.0 + 1.0 / 3600, 10.0, 20.5),                # 1" from the click, faint
            _row(3, 100.0, 10.0 + 20.0 / 3600, 15.0),               # a neighbour 20" away
            _row(4, 100.0, 10.0 + 40.0 / 3600, 12.0)]               # outside 30"
    asked = []
    monkeypatch.setattr(gaia, "query", lambda q, **kw: asked.append(q) or rows)
    out = gaia.star(100.0, 10.0, epoch=2026.0)
    assert "pm>300.0" in asked[0]
    s = out["star"]
    assert s["source_id"] == "1" and s["sep"] < 0.5
    assert s["dist_pc"] == 2.0 and abs(s["abs_g"] - (9.0 + 5 * math.log10(500) - 10)) < 1e-3
    assert [n["source_id"] for n in out["neighbours"]] == ["2", "3"]
    assert out["n_near"] == 3


def test_star_none_when_nothing_close(monkeypatch):
    monkeypatch.setattr(gaia, "query", lambda q, **kw: [_row(3, 100.0, 10.0 + 20.0 / 3600, 15.0)])
    out = gaia.star(100.0, 10.0, epoch=2016.0)
    assert out["star"] is None and len(out["neighbours"]) == 1


def test_abs_g():
    assert gaia.abs_g(10.0, 100.0) == 10.0
    assert gaia.abs_g(10.0, -1.0) is None and gaia.abs_g(None, 5.0) is None
