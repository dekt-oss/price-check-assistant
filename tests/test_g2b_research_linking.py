from purchase_price.services.g2b_market_models import G2BResearchRecord, G2BResearchSource
from purchase_price.services.g2b_research_linking import link_procurement_cases


def test_bid_and_award_link_only_by_explicit_notice_number() -> None:
    bid = G2BResearchRecord(
        source_type=G2BResearchSource.BID_NOTICE,
        source_record_id="bid:1",
        bid_notice_no="R26BK12345678",
        title="가스마취기 구매",
    )
    award = G2BResearchRecord(
        source_type=G2BResearchSource.AWARD,
        source_record_id="award:1",
        bid_notice_no="R26BK12345678",
        title="가스마취기 구매",
    )
    same_title_wrong_notice = G2BResearchRecord(
        source_type=G2BResearchSource.AWARD,
        source_record_id="award:2",
        bid_notice_no="R26BK99999999",
        title="가스마취기 구매",
    )

    cases = link_procurement_cases([bid, award, same_title_wrong_notice])
    linked = next(case for case in cases if case.bid_notice_no == "R26BK12345678")

    assert linked.bid_notices == (bid,)
    assert linked.awards == (award,)
    assert same_title_wrong_notice not in linked.awards


def test_prespec_bid_notice_list_can_join_multiple_explicit_notices() -> None:
    prespec = G2BResearchRecord(
        source_type=G2BResearchSource.PRESPEC,
        source_record_id="prespec:1",
        bid_notice_no="R26BK12345678, R26BK87654321",
    )

    cases = link_procurement_cases([prespec])

    assert {case.bid_notice_no for case in cases} == {"R26BK12345678", "R26BK87654321"}
    assert all(case.prespecs == (prespec,) for case in cases)
