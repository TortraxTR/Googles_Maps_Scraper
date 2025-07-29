UI_SELECTORS = {
    "search_input": '//input[@id="searchboxinput"]',
    "search_results_list": '//a[contains(@href, "https://www.google.com/maps/place")]',
    "business_name": 'h1.DUwDvf,h1.lfPIob',  # Added a fallback selector
    "address": '//button[@data-item-id="address"]//div[contains(@class, "fontBodyMedium")]',
    "website": '//a[@data-item-id="authority"]//div[contains(@class, "fontBodyMedium")]',
    "phone_number": '//button[contains(@data-item-id, "phone:tel:")]//div[contains(@class, "fontBodyMedium")]',
    "reviews": '//button[contains(@class, "fontTitleSmall")]//span'
}