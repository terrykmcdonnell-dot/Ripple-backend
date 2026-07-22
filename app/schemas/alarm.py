
    category: str | None = Field(default=None, description="Legacy category name; resolved to id via the category table")
    category_id: int | None = Field(default=None, description="Preferred category id; must be system or owned by user")
    category_id: Optional[int] = Field(default=None, description="Preferred category id; must be system or owned by user")
    category_id: int
    category_icon: str = "⭐"
    category_color_key: str = "purple"