"""
Retired. The original demo scraper created banks directly with its own
duplicate rule and bypassed validation, review and source records.

Scraping now lives in the ``intake`` app (Admin Scraper page and the
``run_intake_worker`` command). This stub only fails loudly if something
still calls the old function.
"""


def scrape_public_banks(target_url=None):
    raise RuntimeError(
        "scrape_public_banks has been retired. Use the Admin Scraper page "
        "(Data > Scraper) and the intake background worker instead."
    )
