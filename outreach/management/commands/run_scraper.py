from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Disabled. The old demo scraper wrote banks directly with its own duplicate "
        "rule and a browser-style user agent. Use the Admin Scraper page or "
        "'scrape_banks --queue' instead."
    )

    def add_arguments(self, parser):
        parser.add_argument("--url", type=str, default=None, help="Ignored (command disabled).")

    def handle(self, *args, **options):
        from intake import legacy

        raise legacy.direct_write_disabled(
            "run_scraper",
            "Use the Admin Scraper page (Data > Scraper) or 'python manage.py scrape_banks --region Victoria "
            "--queue --admin-email <admin>' and start the worker with 'python manage.py run_intake_worker'.",
        )
