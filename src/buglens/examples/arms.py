from buglens.agent import LangGraphRunner, SubAgentConfig


def main():
    runner = LangGraphRunner()
    cfg = SubAgentConfig()
    monitoring = runner._build_monitoring_service(cfg)
    # runner._arms_rum_search_errors({})
    # BUGLENS_RUM_SLS_PROJECT=
    # BUGLENS_RUM_SLS_LOGSTORE=
    project, logstore = "", ""
    """
    {
        "name": "arms_rum_search_errors",
        "arguments": {
            "time_from_ms": 1779429372877,
            "time_to_ms": 1779432972877,
            "app": "monitor-example",
            "page": "/home",
            "query": "RUM_SYNC_ERROR",
            "page_size": 20,
            "reverse": true
        }
    }
    """
    x = monitoring.sls_search_logs(
        project=project,
        logstore=logstore,
        time_from_ms=1779414972000,
        time_to_ms=1779465372000,
        # page_token=None,
        page_size=20,
        reverse=True,
        extra_query={"query": "RUM_SYNC_ERROR"},
    )
    print(x)

if __name__ == '__main__':
    main()