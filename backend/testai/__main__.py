"""Entry point: python -m testai [command]"""
import sys


def main():
    if len(sys.argv) < 2:
        print("""
  TestAI-Pro — AI-Powered QA Automation Platform

  Commands:
    python -m testai server            Start the dashboard at http://localhost:8000
    python -m testai demo              Run demo (generates sample events + clusters them)
    python -m testai demo --use-llm    Run demo with real LLM labeling
    python -m testai demo-showcase     Rich showcase demo (3 apps, 12 journeys, run history)
    python -m testai demo-showcase --clean  Wipe DB first, then populate showcase
    python -m testai cluster <file.json>  Process a captured events file
    python -m testai auth <url>        Generate auth.json for an app (opens browser for login)
    python -m testai auth              List saved auth states
        """)
        return

    cmd = sys.argv[1]

    if cmd == "demo":
        from testai.demo import generate_demo_file
        from pathlib import Path

        demo_file = Path("demo-events.json")
        generate_demo_file(str(demo_file))

        if "--use-llm" in sys.argv:
            from testai.cluster.pipeline import run_pipeline
            run_pipeline(str(demo_file))
        else:
            from testai.cluster.pipeline_local import run_pipeline_local
            run_pipeline_local(str(demo_file))

    elif cmd == "demo-showcase":
        from testai.demo_showcase import run_showcase
        clean = "--clean" in sys.argv
        run_showcase(clean=clean)

    elif cmd == "server":
        from testai.server import main as serve
        serve()

    elif cmd == "cluster":
        if len(sys.argv) < 3:
            print("Usage: python -m testai cluster <events.json> [--use-llm]")
            return
        events_file = sys.argv[2]
        if "--use-llm" in sys.argv:
            from testai.cluster.pipeline import run_pipeline
            run_pipeline(events_file)
        else:
            from testai.cluster.pipeline_local import run_pipeline_local
            run_pipeline_local(events_file)

    elif cmd == "auth":
        from testai.auth import main as auth_main
        sys.argv = sys.argv[1:]
        auth_main()

    else:
        print(f"Unknown command: {cmd}")
        print("Run 'python -m testai' for help.")


if __name__ == "__main__":
    main()
