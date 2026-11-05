from scripts.inspect_domain_intersection import show_report, get_rank


def test_rank_direct_and_nested():
    assert get_rank({'rank_group': 2}) == 2
    assert get_rank({'serp_item': {'rank_group': 5}}) == 5
    assert get_rank({'rank_group': None}) is None


def test_report_leaders_and_missing():
    data = {
        'target1': 'hollywoodbets.net', 'target2': 'betway.co.za',
        'items': [
            {'keyword': 'aviator', 'search_volume': 100, 'first_domain_serp_element': {'rank_group': 2}, 'second_domain_serp_element': {'rank_group': 1}},
            {'keyword': 'aviator demo', 'search_volume': 50, 'first_domain_serp_element': {'serp_item': {'rank_group': 1}}, 'second_domain_serp_element': {'serp_item': {'rank_group': 4}}},
            {'keyword': 'aviator login', 'search_volume': None, 'first_domain_serp_element': None, 'second_domain_serp_element': None},
        ],
    }
    report = show_report(data, 'aviator', 10)
    assert 'Domain 1 ahead: 1' in report
    assert 'Domain 2 ahead: 1' in report
    assert 'Rank comparison unavailable: 1' in report
    assert 'Validation warnings: 1' in report
