from analysis.final_report import generate_report


def sample():
    def audit(url):
        return {"status":"usable","target_verified":True,"final_url_verified":True,
                "ranking_url":url,"scores":{},"lab_metrics":{}}
    ours="https://example.org/aviator"
    comp="https://example.net/aviator"
    return {"keyword":"aviator","primary_ranking_urls":{"ours":ours,"benchmark":comp},
            "evidence_quality":{"lighthouse_ours_mobile":"usable","lighthouse_benchmark_mobile":"usable"},
            "page_level_evidence":{"lighthouse":{"ours":{"mobile":audit(ours)},"benchmark":{"mobile":audit(comp)}}},
            "technical_comparison":{"mobile":{"detailed_analysis":{
                "status":"usable","scope":"exact_serp_pages_mobile_lab",
                "investigations":[{"title":"Review JS bundle","priority":"high","audit_id":"unused-javascript",
                    "measurement":{"display":"Est savings of 1,108 KiB"},
                    "affected_resources":[{"url":"https://example.org/main.js","wastedBytes":10000}],
                    "actions":["Check code splitting"],"validation":"Repeat audits",
                    "confidence":"investigation_only","note":"Lab only"}]}}}}


def test_renders_verified_investigation():
    text=generate_report(sample())
    assert "Review JS bundle" in text
    assert "1,108 KiB" in text
    assert "example.org/main.js" in text
    assert "Check code splitting" in text
    assert "Repeat audits" in text


def test_withholds_unverified_audit():
    data=sample()
    data["evidence_quality"]["lighthouse_ours_mobile"]="unusable"
    text=generate_report(data)
    assert "Detailed technical investigations withheld" in text
    assert "Review JS bundle" not in text


def test_withholds_wrong_scope():
    data=sample()
    data["technical_comparison"]["mobile"]["detailed_analysis"]["scope"]="other"
    assert "Detailed technical investigations withheld" in generate_report(data)


def test_escapes_untrusted_resource():
    data=sample()
    data["technical_comparison"]["mobile"]["detailed_analysis"]["investigations"][0]["affected_resources"][0]["url"]="<script>|unsafe"
    text=generate_report(data)
    assert "&lt;script&gt;\\|unsafe" in text
    assert "<script>" not in text
