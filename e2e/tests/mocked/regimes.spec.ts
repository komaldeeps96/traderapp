import { expect, test } from '../../fixtures/test';

/**
 * The same strip across the price regimes it has to work in.
 *
 * Every read added for the momentum workflow is scale-sensitive in some way,
 * and most of the scale sensitivity is not linear. The LULD band tier is set
 * by three brackets of the previous close, the quoting tick changes at $1,
 * headroom is a percentage of a price that ranges over two orders of
 * magnitude, and the baby-shelf cap turns on a dollar figure rather than a
 * ratio. A suite that only ever sees a ten-dollar stock proves none of it.
 *
 * Each block below is a different ticker at a different price, driven through
 * the same assertions.
 */

const REGIMES = [
  {
    symbol: 'SUBP',
    price: 0.62,
    prevClose: 0.55,
    label: 'sub-dollar',
    // Below $0.75 the band is a flat 15 cents, not a percentage at all.
    band: { pct: null, cents: 15, text: 'LULD 15¢' },
  },
  {
    symbol: 'WIDE',
    price: 2.4,
    prevClose: 2.1,
    label: 'the wide 20% tier',
    band: { pct: 20, cents: null, text: 'LULD 20%' },
  },
  {
    symbol: 'SWEET',
    price: 7.5,
    prevClose: 6.2,
    label: 'the $5–10 sweet spot',
    band: { pct: 10, cents: null, text: 'LULD 10%' },
  },
  {
    symbol: 'RICH',
    price: 68,
    prevClose: 61,
    label: 'above the price band',
    band: { pct: 10, cents: null, text: 'LULD 10%' },
  },
] as const;

for (const regime of REGIMES) {
  test.describe(`${regime.label} — ${regime.symbol} at $${regime.price}`, () => {
    test.use({
      backendOptions: { sessionSymbol: regime.symbol, basePrice: regime.price },
    });

    test('renders a price at the right precision', async ({ terminal }) => {
      await terminal.waitForChart();
      const last = await terminal.page.getByTestId('tp-last').textContent();
      // Sub-dollar names quote in hundredths of a cent, so two decimals
      // would put a level and the price standing on it at the same number.
      expect(last).toMatch(regime.price < 1 ? /^\d\.\d{4}$/ : /^\d+\.\d{2}$/);
    });

    test('names the LULD tier its previous close puts it in', async ({ terminal, backend }) => {
      await terminal.waitForChart();
      await backend.pushInfo({
        halt_active: true,
        prev_close: regime.prevClose,
        halt_band_pct: regime.band.pct,
        halt_band_cents: regime.band.cents,
        halt_ref: regime.price,
        halt_up: regime.band.pct ? regime.price * (1 + regime.band.pct / 100) : regime.price + 0.15,
        halt_down: regime.band.pct
          ? regime.price * (1 - regime.band.pct / 100)
          : regime.price - 0.15,
      });

      const chip = terminal.page.getByTestId('tp-halt');
      await expect(chip).toContainText(regime.band.text);
      // Distances are magnitudes; the arrows carry the direction.
      await expect(chip).not.toContainText('+');
    });

    test('measures headroom against its own ladder', async ({ terminal }) => {
      await terminal.waitForChart();
      const chip = terminal.page.getByTestId('tp-headroom');
      await expect(chip).toBeVisible();
      // Whatever the price, the read is a percentage or open sky — never a
      // raw price, and never a negative distance.
      await expect(chip).toHaveText(/^(ROOM \d+\.\d%|BLUE SKY)$/);
    });

    test('keeps the strip on three rows', async ({ terminal }) => {
      // Every value goes through a bounded formatter so a wide number costs
      // characters rather than a row. A sixty-eight dollar stock and a
      // sixty-two cent one must not lay out differently.
      await terminal.waitForChart();
      const box = await terminal.page.getByTestId('top-panel').boundingBox();
      expect(box!.height).toBeLessThan(80);
    });
  });
}
