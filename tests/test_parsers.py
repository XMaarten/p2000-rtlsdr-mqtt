from p2000_receiver.parsers import parse_deflex_log_line, parse_multimon_line


def test_parse_multimon_single():
    page = parse_multimon_line(
        "FLEX|2021-06-28 16:50:07|1600/2/K/A|12.077|001180000|ALN|TESTOPROEP"
    )
    assert page is not None
    assert page.capcodes == ("001180000",)
    assert page.body == "TESTOPROEP"


def test_parse_multimon_multiple_and_pipe_in_body():
    page = parse_multimon_line(
        "FLEX|2021-06-28 16:50:35|1600/2/K/A|12.092|"
        "002029568 000126999 000126164|ALN|A2 melding | extra"
    )
    assert page is not None
    assert page.capcodes == ("002029568", "000126999", "000126164")
    assert page.body == "A2 melding | extra"


def test_malformed_multimon_is_ignored():
    assert parse_multimon_line("FLEX|broken") is None
    assert parse_multimon_line("noise") is None


def test_deflex_does_not_fabricate_capcode():
    page = parse_deflex_log_line("2026-08-22T10:00:00Z FLEX|169650000|123|A|0|ALN|P 1 TEST")
    assert page is not None
    assert page.capcodes == ()
    assert page.confidence == "A"
