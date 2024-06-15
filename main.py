from pyfiglet import figlet_format
from core import get_cfg, parse_config, Runner

def main():
    # Acii art
    print(figlet_format("CARD PROXY PRINTER", font="slant", width=150))

    # Config
    base_config = get_cfg()
    config = parse_config(base_config)

    # Runner
    runner = Runner(config)
    runner.run()

if __name__ == "__main__":
    main()
