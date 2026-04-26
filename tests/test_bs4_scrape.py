import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _bs4_scrape import scrape_tables, scrape_selector, scrape_lists, scrape_schema


TABLE_HTML = """
<html><body>
<table>
  <tr><th>Name</th><th>Age</th></tr>
  <tr><td>Alice</td><td>30</td></tr>
  <tr><td>Bob</td><td>25</td></tr>
</table>
</body></html>
"""

LIST_HTML = """
<html><body>
<ul>
  <li>Apple</li>
  <li>Banana</li>
</ul>
<ol>
  <li>First</li>
  <li>Second</li>
</ol>
</body></html>
"""

SELECTOR_HTML = """
<html><body>
<h1 class="title">Hello World</h1>
<p>Some text</p>
</body></html>
"""

SCHEMA_HTML = """
<html><body>
<h1>Product</h1>
<span class="price">$29.99</span>
<nav><a href="/about">About</a><a href="/contact">Contact</a></nav>
</body></html>
"""


def test_scrape_tables_extracts_table():
    result = scrape_tables(TABLE_HTML)
    assert result.status == "ok"
    assert len(result.tables) == 1
    assert result.tables[0][0] == ["Name", "Age"]
    assert result.tables[0][1] == ["Alice", "30"]


def test_scrape_tables_returns_partial_when_no_tables():
    result = scrape_tables("<html><body><p>no table here</p></body></html>")
    assert result.status == "partial"


def test_scrape_tables_markdown_is_valid():
    result = scrape_tables(TABLE_HTML)
    assert "|" in result.markdown
    assert "---" in result.markdown
    assert "Name" in result.markdown


def test_scrape_selector_returns_matching_text():
    result = scrape_selector(SELECTOR_HTML, ".title")
    assert result.status == "ok"
    assert "Hello World" in result.text


def test_scrape_selector_returns_partial_when_no_match():
    result = scrape_selector(SELECTOR_HTML, ".nonexistent")
    assert result.status == "partial"


def test_scrape_lists_extracts_items():
    result = scrape_lists(LIST_HTML)
    assert result.status == "ok"
    assert "Apple" in result.markdown
    assert "First" in result.markdown


def test_scrape_schema_extracts_multiple_fields():
    schema = {
        "title": "h1",
        "price": ".price",
        "links": {"selector": "nav a", "attribute": "href", "multiple": True},
    }
    result = scrape_schema(SCHEMA_HTML, schema)
    assert result.status == "ok"
    import json
    data = json.loads(result.text)
    assert data["title"] == "Product"
    assert data["price"] == "$29.99"
    assert "/about" in data["links"]


def test_scrape_schema_sets_none_for_missing_selector():
    schema = {"missing_field": ".does-not-exist"}
    result = scrape_schema(SCHEMA_HTML, schema)
    import json
    data = json.loads(result.text)
    assert data["missing_field"] is None
