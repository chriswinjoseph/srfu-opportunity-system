import requests
from bs4 import BeautifulSoup
from .models import Bank

# Local mock HTML directory for safe development testing
MOCK_PUBLIC_DIRECTORY = """
<div class="directory-list">
    <div class="branch-card">
        <span class="bank-name">Bendigo Community Bank Clifton Hill</span>
        <span class="region">Victoria</span>
        <a class="email" href="mailto:cliftonhill@example.com">cliftonhill@example.com</a>
        <span class="phone">03 9482 9000</span>
        <a class="website" href="https://www.bendigobank.com.au">Website</a>
    </div>
    <div class="branch-card">
        <span class="bank-name">Community Bank Strathmore</span>
        <span class="region">Victoria</span>
        <a class="email" href="mailto:strathmore@example.com">strathmore@example.com</a>
        <span class="phone">03 9374 2000</span>
        <a class="website" href="https://www.bendigobank.com.au">Website</a>
    </div>
    <div class="branch-card">
        <span class="bank-name">Community Bank Fremantle</span>
        <span class="region">Western Australia</span>
        <a class="email" href="mailto:fremantle@example.com">fremantle@example.com</a>
        <span class="phone">08 9433 5000</span>
        <a class="website" href="https://www.bendigobank.com.au">Website</a>
    </div>
</div>
"""


def scrape_public_banks(target_url=None):
    created_count = 0
    skipped_count = 0
    html_content = None

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
    }

    # Attempt live request if an actual external URL is passed
    if target_url:
        try:
            response = requests.get(target_url, headers=headers, timeout=10)
            if response.status_code == 200:
                html_content = response.text
            else:
                return {'created': 0, 'skipped': 0, 'error': f"HTTP status {response.status_code}"}
        except Exception as exc:
            return {'created': 0, 'skipped': 0, 'error': str(exc)}
    else:
        # Fall back to local mock HTML so testing works without external network dependencies
        html_content = MOCK_PUBLIC_DIRECTORY

    soup = BeautifulSoup(html_content, 'html.parser')
    entries = soup.select('.branch-card, .bank-listing, tr.branch-row')

    for entry in entries:
        name_el = entry.select_one('.bank-name, .branch-name, td.name')
        region_el = entry.select_one('.region, .state, td.region')
        email_el = entry.select_one('.email, td.email, a[href^="mailto:"]')
        phone_el = entry.select_one('.phone, td.phone, a[href^="tel:"]')
        link_el = entry.select_one('a.website, td.website a')

        bank_name = name_el.get_text(strip=True) if name_el else None
        region = region_el.get_text(strip=True) if region_el else 'Victoria'

        if not bank_name:
            skipped_count += 1
            continue

        public_email = email_el.get_text(strip=True) if email_el else ""
        public_phone = phone_el.get_text(strip=True) if phone_el else ""
        website_url = link_el.get('href') if link_el else ""

        _, created = Bank.objects.get_or_create(
            bank_name=bank_name,
            region=region,
            defaults={
                'public_email': public_email,
                'public_phone': public_phone,
                'website_url': website_url,
                'source_url': target_url or 'Local Public Directory Seed',
                'contact_status': "not_yet_contacted",
            }
        )

        if created:
            created_count += 1
        else:
            skipped_count += 1

    return {'created': created_count, 'skipped': skipped_count, 'error': None}