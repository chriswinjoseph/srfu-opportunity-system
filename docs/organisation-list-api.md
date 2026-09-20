# Organisation List and Status Filtering API

## Purpose

This API provides a single authenticated endpoint for listing banks, branches and clubs. It supports searching, filtering, sorting and pagination for use by the outreach dashboard and future frontend components.

Organisation contact status and opportunity outcome remain separate:

- `contact_status` records whether outreach occurred.
- `opportunity_outcome` records the response to that outreach.
- `status_conflict` identifies records that require review.

## Endpoint

```http
GET /outreach/api/organisations/
```

Django URL name:

```text
organisation_list_api
```

## Authentication and Request Method

The endpoint requires an authenticated user.

- A logged-out request is redirected to the login page.
- Only `GET` requests are accepted.
- Other methods, including `POST`, return HTTP `405 Method Not Allowed`.

## Query Parameters

| Parameter | Description | Allowed values/default |
| --- | --- | --- |
| `q` | Case-insensitive organisation-name search | Any text |
| `type` | Filter by organisation type | `bank`, `branch`, `club` |
| `region` | Case-insensitive region search | Any text |
| `status` | Filter by organisation contact status | `not_yet_contacted`, `contacted` |
| `sort_by` | Field used for sorting | `name`, `region`, `type`, `status`; default: `name` |
| `sort_dir` | Sorting direction | `asc`, `desc`; default: `asc` |
| `page` | Requested result page | Positive integer; default: `1` |
| `page_size` | Number of records per page | Positive integer; default: `10`; maximum: `50` |

## Status Filtering

The `status` parameter filters the organisation's actual `contact_status`. It does not filter opportunity outcomes such as `interested`.

A single status can be supplied:

```http
GET /outreach/api/organisations/?status=contacted
```

Multiple statuses can be supplied as repeated parameters:

```http
GET /outreach/api/organisations/?status=contacted&status=not_yet_contacted
```

They can also be supplied as a comma-separated value:

```http
GET /outreach/api/organisations/?status=contacted,not_yet_contacted
```

## Combined Filter Example

```http
GET /outreach/api/organisations/?q=Alpha&type=bank&region=Victoria&status=contacted&sort_by=name&sort_dir=asc&page=1&page_size=10
```

## Successful Response

A successful request returns HTTP `200 OK`.

Example:

```json
{
  "filters": {
    "q": "Alpha",
    "type": "bank",
    "region": "Victoria",
    "status": [
      "contacted"
    ]
  },
  "sorting": {
    "sort_by": "name",
    "sort_dir": "asc"
  },
  "pagination": {
    "page": 1,
    "page_size": 10,
    "total_items": 1,
    "total_pages": 1,
    "has_next": false,
    "has_previous": false
  },
  "results": [
    {
      "id": 1,
      "content_type_id": 7,
      "type": "bank",
      "name": "Alpha Bank",
      "region": "Victoria",
      "email": "alpha@example.com",
      "phone": "0311111111",
      "contact_status": "contacted",
      "contact_status_label": "Contacted",
      "opportunity_outcome": "interested",
      "status_conflict": false,
      "status_label": "Interested"
    }
  ]
}
```

The numeric identifiers in the response depend on the records in the database.

## Contact Status and Opportunity Outcome

The API preserves the status separation introduced by the contact-status transition safeguards.

Valid organisation contact statuses are:

- `not_yet_contacted`
- `contacted`

Opportunity outcomes are returned separately and may include:

- `interested`
- `not_interested`
- `do_not_contact`

An organisation that is `not_yet_contacted` but has a recorded opportunity outcome is returned with:

```json
{
  "contact_status": "not_yet_contacted",
  "opportunity_outcome": "interested",
  "status_conflict": true,
  "status_label": "Needs Review"
}
```

The API does not silently change either status to resolve this conflict.

## Validation and Error Responses

Invalid input returns HTTP `400 Bad Request` with a structured JSON response.

The endpoint rejects:

- Unknown organisation types
- Unknown contact-status values
- Opportunity outcomes supplied as contact-status filters
- Unknown sorting fields
- Invalid sorting directions
- Non-numeric or non-positive page values
- Non-numeric or non-positive page-size values
- A page size greater than 50
- Page numbers outside the available range

An empty search result is valid. Page 1 returns an empty `results` list. Requesting a later page for the same empty result set returns HTTP `400`.

## Sorting

Sorting is deterministic. When multiple records have the same primary sorting value, secondary values are used to keep their order consistent.

Examples:

```http
GET /outreach/api/organisations/?sort_by=name&sort_dir=desc
```

```http
GET /outreach/api/organisations/?sort_by=region&sort_dir=asc
```

## Automated Test Coverage

The API tests cover:

- Logged-out access
- GET-only enforcement
- Returning banks, branches and clubs
- Separation of contact status and opportunity outcome
- Status-conflict reporting
- Single status filtering
- Repeated and comma-separated status filtering
- Combined search, type, region and status filters
- Invalid type and status values
- Invalid sorting fields and directions
- Descending sorting
- Pagination
- Invalid and out-of-range pagination
- Empty result sets

The completed project test run contained 38 tests, and all tests passed.

## Implementation Files

- `outreach/views.py`
- `outreach/urls.py`
- `outreach/tests.py`

## Code Commit

[Add organisation list and status filtering API](https://github.com/chriswinjoseph/srfu-opportunity-system/commit/0d62a67a1a86fc6c9ac28248cc217a79a83e6bcf)