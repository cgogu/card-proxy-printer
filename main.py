from core import get_cfg, Runner

def main():
    config = get_cfg()
    runner = Runner(config)
    runner.run()

if __name__ == "__main__":
    main()
