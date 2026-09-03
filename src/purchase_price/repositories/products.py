from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from purchase_price.models import Product
from purchase_price.schemas import ProductQuery


def find_products(session: Session, query: ProductQuery, limit: int = 50) -> list[Product]:
    stmt: Select[tuple[Product]] = select(Product)
    filters = []
    if query.product_name:
        filters.append(Product.product_name.ilike(f"%{query.product_name}%"))
    if query.manufacturer:
        filters.append(Product.manufacturer.ilike(f"%{query.manufacturer}%"))
    if query.model_name:
        filters.append(Product.model_name.ilike(f"%{query.model_name}%"))
    if query.specification:
        filters.append(Product.specification.ilike(f"%{query.specification}%"))
    if filters:
        stmt = stmt.where(or_(*filters))
    return list(session.scalars(stmt.limit(limit)).all())
