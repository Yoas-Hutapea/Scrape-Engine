from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Export / row headers (thumbnail = Product Image 1 only)
EXCEL_HEADERS: list[str] = [
    "Product Name",
    "Long Description",
    "short description",
    "Product Source Link",
    "Variation Name 1",
    "Variation Option 1",
    "Variation Name 2",
    "Variation Option 2",
    "Variation Name 3",
    "Variation Option 3",
    "price",
    "Discount",
    "Currency",
    "Stock",
    "SKU",
    "Package Weight",
    "Package Length",
    "Package Width",
    "Package Height",
    "Product Image 1",
]

MAX_IMAGES = 1
MAX_VARIATION_DIMS = 3


@dataclass
class Variant:
    """One sellable SKU / variation combination."""

    options: list[tuple[str, str]] = field(default_factory=list)
    price: float | None = None
    discount: float | None = None
    currency: str = "IDR"
    stock: float | None = None
    sku: str | None = None
    weight: str | None = None
    length: str | None = None
    width: str | None = None
    height: str | None = None
    images: list[str] = field(default_factory=list)


@dataclass
class Product:
    name: str
    source_link: str
    long_description: str = ""
    short_description: str = ""
    images: list[str] = field(default_factory=list)
    weight: str | None = None
    length: str | None = None
    width: str | None = None
    height: str | None = None
    currency: str = "IDR"
    variants: list[Variant] = field(default_factory=list)
    price: float | None = None
    discount: float | None = None
    stock: float | None = None
    sku: str | None = None


def _first_image(urls: list[str]) -> str | None:
    for u in urls:
        if u:
            return u
    return None


def _html_to_short(text: str, limit: int = 500) -> str:
    if not text:
        return ""
    import re

    plain = re.sub(r"<[^>]+>", "", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) <= limit:
        return plain
    return plain[:limit].rstrip()


def flatten_product(product: Product) -> list[dict[str, Any]]:
    """Flatten a Product into row dicts (one per variant). Thumbnail = Product Image 1 only."""
    thumb = _first_image(product.images)
    short = product.short_description or _html_to_short(product.long_description)

    variants = product.variants
    if not variants:
        variants = [
            Variant(
                price=product.price,
                discount=product.discount,
                currency=product.currency,
                stock=product.stock,
                sku=product.sku,
                weight=product.weight,
                length=product.length,
                width=product.width,
                height=product.height,
            )
        ]

    rows: list[dict[str, Any]] = []
    for variant in variants:
        opts = list(variant.options)[:MAX_VARIATION_DIMS]
        while len(opts) < MAX_VARIATION_DIMS:
            opts.append(("", ""))

        # Prefer product thumbnail; fall back to first variation image if needed
        image = thumb or _first_image(variant.images)

        rows.append(
            {
                "Product Name": product.name,
                "Long Description": product.long_description,
                "short description": short,
                "Product Source Link": product.source_link,
                "Variation Name 1": opts[0][0] or None,
                "Variation Option 1": opts[0][1] or None,
                "Variation Name 2": opts[1][0] or None,
                "Variation Option 2": opts[1][1] or None,
                "Variation Name 3": opts[2][0] or None,
                "Variation Option 3": opts[2][1] or None,
                "price": variant.price if variant.price is not None else product.price,
                "Discount": variant.discount if variant.discount is not None else product.discount,
                "Currency": variant.currency or product.currency or "IDR",
                "Stock": variant.stock if variant.stock is not None else product.stock,
                "SKU": variant.sku or product.sku,
                "Package Weight": variant.weight or product.weight,
                "Package Length": variant.length or product.length,
                "Package Width": variant.width or product.width,
                "Package Height": variant.height or product.height,
                "Product Image 1": image,
            }
        )
    return rows


def flatten_products(products: list[Product]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for product in products:
        rows.extend(flatten_product(product))
    return rows
