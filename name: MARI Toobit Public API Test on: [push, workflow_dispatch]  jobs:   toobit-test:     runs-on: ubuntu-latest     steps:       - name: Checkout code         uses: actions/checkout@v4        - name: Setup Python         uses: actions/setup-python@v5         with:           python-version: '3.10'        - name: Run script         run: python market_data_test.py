name: MARI Toobit Public API Test
on: [push, workflow_dispatch]

jobs:
  toobit-test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Run script
        run: python market_data_test.py
