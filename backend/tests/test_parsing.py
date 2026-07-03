import pytest

from app.pvgis import PVGISError, parse_pvcalc
from tests.fixtures import pvcalc_response


class TestParsePVcalc:
    def test_extracts_angles_and_totals(self):
        result = parse_pvcalc(pvcalc_response(slope=35, azimuth=0))
        assert result["slope_deg"] == 35.0
        assert result["azimuth_deg"] == 0.0
        assert result["annual_production_kwh"] == pytest.approx(6832, rel=0.01)
        assert result["hsp_daily_avg"] == 4.46
        assert result["elevation_m"] == 250.0

    def test_monthly_sorted_and_complete(self):
        result = parse_pvcalc(pvcalc_response())
        months = [m["month"] for m in result["monthly"]]
        assert months == list(range(1, 13))
        july = result["monthly"][6]
        assert july["production_kwh"] == pytest.approx(190.18 * 4.2, rel=0.01)
        assert july["irradiation_kwh_m2"] == 190.18

    def test_malformed_response_raises(self):
        with pytest.raises(PVGISError):
            parse_pvcalc({"outputs": {}})

