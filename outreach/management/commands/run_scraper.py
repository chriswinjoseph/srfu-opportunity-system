from django.core.management.base import BaseCommand
from outreach.scraper import scrape_public_banks


class Command(BaseCommand):
    help = "Run the public directory scraper for community banks"

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            type=str,
            default=None,
            help='Target public directory URL to scrape'
        )

    def handle(self, *args, **options):
        self.stdout.write("Running public bank directory scraper...")
        result = scrape_public_banks(target_url=options['url'])

        if result['error']:
            self.stdout.write(self.style.WARNING(f"Scraper notice: {result['error']}"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Completed: {result['created']} added, {result['skipped']} skipped."
            ))