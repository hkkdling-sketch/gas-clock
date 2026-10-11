# GasClock

**When is Ethereum gas cheapest?**

A single static page that answers that question using seven days of on-chain data.

Most gas trackers show you the price *right now*. That is the least useful number on
the page, because you cannot change the past — you can only decide *when* to send a
transaction. GasClock samples roughly 670 blocks across the last week and lines them
up by hour-of-day and day-of-week, so the cheapest windows are visible at a glance.

## What it does

- Reads the EIP-1559 `baseFeePerGas` straight from Ethereum block headers
- Samples one block every ~15 minutes for the last 7 days (~670 samples)
- Aggregates into a 7 x 24 heatmap of average base fee
- Highlights the cheapest and most expensive hour of the week
- Renders a 24-hour bar chart of average gas by hour
- Lets you switch between UTC and your local timezone

No wallet connection. No signup. No analytics. No API keys. No build step.

## Data source

Public JSON-RPC endpoints, no authentication required:

- `https://ethereum-rpc.publicnode.com`
- `https://rpc.flashbots.net`

Blocks are fetched in batches of 30 via `eth_getBlockByNumber`. Each block header
carries both the timestamp and the base fee, so a single request yields everything
the heatmap needs.

Sampling is deliberate: an earlier version used `eth_feeHistory` to pull all ~50,000
blocks in the window, which meant ~50 heavy requests. Public nodes rate-limit that
hard. ~23 light batched requests for ~670 samples gives the same shape for a fraction
of the load.

## Run it locally

Requires Python 3.9+ and nothing else.

```bash
python scripts/fetch_gas.py
```

That writes `data/gas.json`. Then serve the folder over HTTP — opening `index.html`
directly will not work, because `fetch()` is blocked on `file://` URLs:

```bash
python -m http.server 8099
```

Open `http://127.0.0.1:8099`.

## Deployment

The repo is designed to run for free with no server:

1. Push to GitHub.
2. Enable GitHub Pages for the repository root.
3. The included workflow (`.github/workflows/update.yml`) refreshes `data/gas.json`
   every 15 minutes and commits the result, which Pages then serves.

Total running cost: zero.

## Notes and limitations

- **Mainnet only.** Rollups (Base, Arbitrum, Optimism, and friends) have separate fee
  markets and are not reflected here.
- **Base fee only.** Your wallet adds a priority tip on top. This page does not track
  tips, so the numbers are a floor, not a total.
- **It is a summary, not a forecast.** Everything here already happened on-chain.
  Nothing on this page predicts future gas prices.
- The heatmap is a rolling window. A single unusual event — an NFT mint, an airdrop
  claim — can skew a cell.

## License

MIT. See `LICENSE`.
