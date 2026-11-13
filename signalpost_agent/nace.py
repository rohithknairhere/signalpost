"""Plain-English NACE Rev. 2 division titles (the first two digits of a Norwegian industry code)."""

DIVISIONS = {
    "01": "crop and animal production", "02": "forestry and logging", "03": "fishing and aquaculture",
    "05": "coal mining", "06": "oil and gas extraction", "07": "metal ore mining", "08": "mining and quarrying",
    "09": "mining support services", "10": "food manufacturing", "11": "beverage manufacturing", "12": "tobacco products",
    "13": "textile manufacturing", "14": "clothing manufacturing", "15": "leather goods manufacturing",
    "16": "wood products manufacturing", "17": "paper products manufacturing", "18": "printing",
    "19": "refined petroleum products", "20": "chemicals manufacturing", "21": "pharmaceuticals manufacturing",
    "22": "rubber and plastic products", "23": "non-metallic mineral products", "24": "basic metals",
    "25": "fabricated metal products", "26": "computer and electronic products", "27": "electrical equipment",
    "28": "machinery and equipment", "29": "motor vehicles", "30": "other transport equipment (including ships)",
    "31": "furniture manufacturing", "32": "other manufacturing", "33": "repair and installation of machinery",
    "35": "electricity, gas and heating supply", "36": "water supply", "37": "sewerage", "38": "waste collection and recycling",
    "39": "remediation services", "41": "building construction", "42": "civil engineering",
    "43": "specialised construction trades", "45": "motor vehicle sales and repair", "46": "wholesale trade",
    "47": "retail trade", "49": "land transport", "50": "water transport", "51": "air transport",
    "52": "warehousing and transport support", "53": "postal and courier services", "55": "accommodation",
    "56": "restaurants and food service", "58": "publishing", "59": "film, video and music production",
    "60": "broadcasting", "61": "telecommunications", "62": "software and IT services", "63": "information services",
    "64": "financial services and holding companies", "65": "insurance and pensions", "66": "auxiliary financial services",
    "68": "real estate", "69": "legal and accounting services", "70": "head offices and management consultancy",
    "71": "architecture and engineering", "72": "scientific research", "73": "advertising and market research",
    "74": "design, photography and other professional services", "75": "veterinary services", "77": "rental and leasing",
    "78": "employment and staffing services", "79": "travel agencies and tour operators", "80": "security services",
    "81": "building services, cleaning and landscaping", "82": "office and business support services",
    "84": "public administration", "85": "education", "86": "health care", "87": "residential care",
    "88": "social work", "90": "arts and entertainment", "91": "libraries, museums and culture",
    "92": "gambling", "93": "sports and recreation", "94": "membership organisations", "95": "repair of household goods",
    "96": "personal services", "97": "households as employers", "99": "international organisations",
}


def division(code: str | None) -> str | None:
    return DIVISIONS.get(str(code or "")[:2])
