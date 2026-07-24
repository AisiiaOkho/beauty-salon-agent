"""
Boundary-resolution metadata for Russian regions.

Relation IDs are intentionally nullable: an unknown relation ID is safer than
an incorrect pinned boundary. The OSM resolver uses these fields in priority
order and requires a confident unique match.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegionMetadata:
    """Metadata used to resolve a region boundary in OSM."""

    name: str
    iso3166_2: str | None = None
    wikidata: str | None = None
    osm_relation_id: int | None = None
    aliases: tuple[str, ...] = ()


REGION_METADATA: dict[str, RegionMetadata] = {
    "Калининградская область": RegionMetadata(
        name="Калининградская область",
        iso3166_2="RU-KGD",
        aliases=("Калининградская обл.", "Kaliningrad Oblast"),
    ),
    "Санкт-Петербург": RegionMetadata(
        name="Санкт-Петербург",
        iso3166_2="RU-SPE",
        aliases=("Санкт Петербург", "Saint Petersburg", "St Petersburg"),
    ),
    "Ленинградская область": RegionMetadata(
        name="Ленинградская область",
        iso3166_2="RU-LEN",
        aliases=("Ленинградская обл.", "Leningrad Oblast"),
    ),
    "Республика Карелия": RegionMetadata(
        name="Республика Карелия",
        iso3166_2="RU-KR",
        aliases=("Карелия", "Karelia"),
    ),
    "Псковская область": RegionMetadata(
        name="Псковская область",
        iso3166_2="RU-PSK",
        aliases=("Псковская обл.", "Pskov Oblast"),
    ),
    "Новгородская область": RegionMetadata(
        name="Новгородская область",
        iso3166_2="RU-NGR",
        aliases=("Новгородская обл.", "Novgorod Oblast"),
    ),
    "Мурманская область": RegionMetadata(
        name="Мурманская область",
        iso3166_2="RU-MUR",
        aliases=("Мурманская обл.", "Murmansk Oblast"),
    ),
    "Вологодская область": RegionMetadata(
        name="Вологодская область",
        iso3166_2="RU-VLG",
        aliases=("Вологодская обл.", "Vologda Oblast"),
    ),
    "Смоленская область": RegionMetadata(
        name="Смоленская область",
        iso3166_2="RU-SMO",
        aliases=("Смоленская обл.", "Smolensk Oblast"),
    ),
    "Тверская область": RegionMetadata(
        name="Тверская область",
        iso3166_2="RU-TVE",
        aliases=("Тверская обл.", "Tver Oblast"),
    ),
    "Москва": RegionMetadata(
        name="Москва",
        iso3166_2="RU-MOW",
        aliases=("Moscow",),
    ),
    "Московская область": RegionMetadata(
        name="Московская область",
        iso3166_2="RU-MOS",
        aliases=("Московская обл.", "Moscow Oblast"),
    ),
    "Брянская область": RegionMetadata(
        name="Брянская область",
        iso3166_2="RU-BRY",
        aliases=("Брянская обл.", "Bryansk Oblast"),
    ),
    "Калужская область": RegionMetadata(
        name="Калужская область",
        iso3166_2="RU-KLU",
        aliases=("Калужская обл.", "Kaluga Oblast"),
    ),
    "Орловская область": RegionMetadata(
        name="Орловская область",
        iso3166_2="RU-ORL",
        aliases=("Орловская обл.", "Oryol Oblast"),
    ),
    "Тульская область": RegionMetadata(
        name="Тульская область",
        iso3166_2="RU-TUL",
        aliases=("Тульская обл.", "Tula Oblast"),
    ),
    "Курская область": RegionMetadata(
        name="Курская область",
        iso3166_2="RU-KRS",
        aliases=("Курская обл.", "Kursk Oblast"),
    ),
    "Белгородская область": RegionMetadata(
        name="Белгородская область",
        iso3166_2="RU-BEL",
        aliases=("Белгородская обл.", "Belgorod Oblast"),
    ),
    "Рязанская область": RegionMetadata(
        name="Рязанская область",
        iso3166_2="RU-RYA",
        aliases=("Рязанская обл.", "Ryazan Oblast"),
    ),
    "Ярославская область": RegionMetadata(
        name="Ярославская область",
        iso3166_2="RU-YAR",
        aliases=("Ярославская обл.", "Yaroslavl Oblast"),
    ),
    "Костромская область": RegionMetadata(
        name="Костромская область",
        iso3166_2="RU-KOS",
        aliases=("Костромская обл.", "Kostroma Oblast"),
    ),
    "Архангельская область": RegionMetadata(
        name="Архангельская область",
        iso3166_2="RU-ARK",
        aliases=("Архангельская обл.", "Arkhangelsk Oblast"),
    ),
    "Ненецкий автономный округ": RegionMetadata(
        name="Ненецкий автономный округ",
        iso3166_2="RU-NEN",
        aliases=("Ненецкий АО", "Nenets Autonomous Okrug"),
    ),
    "Владимирская область": RegionMetadata(
        name="Владимирская область",
        iso3166_2="RU-VLA",
        aliases=("Владимирская обл.", "Vladimir Oblast"),
    ),
    "Ивановская область": RegionMetadata(
        name="Ивановская область",
        iso3166_2="RU-IVA",
        aliases=("Ивановская обл.", "Ivanovo Oblast"),
    ),
    "Нижегородская область": RegionMetadata(
        name="Нижегородская область",
        iso3166_2="RU-NIZ",
        aliases=("Нижегородская обл.", "Nizhny Novgorod Oblast"),
    ),
    "Липецкая область": RegionMetadata(
        name="Липецкая область",
        iso3166_2="RU-LIP",
        aliases=("Липецкая обл.", "Lipetsk Oblast"),
    ),
    "Тамбовская область": RegionMetadata(
        name="Тамбовская область",
        iso3166_2="RU-TAM",
        aliases=("Тамбовская обл.", "Tambov Oblast"),
    ),
    "Воронежская область": RegionMetadata(
        name="Воронежская область",
        iso3166_2="RU-VOR",
        aliases=("Воронежская обл.", "Voronezh Oblast"),
    ),
    "Республика Мордовия": RegionMetadata(
        name="Республика Мордовия",
        iso3166_2="RU-MO",
        aliases=("Мордовия", "Mordovia"),
    ),
    "Пензенская область": RegionMetadata(
        name="Пензенская область",
        iso3166_2="RU-PNZ",
        aliases=("Пензенская обл.", "Penza Oblast"),
    ),
    "Саратовская область": RegionMetadata(
        name="Саратовская область",
        iso3166_2="RU-SAR",
        aliases=("Саратовская обл.", "Saratov Oblast"),
    ),
    "Волгоградская область": RegionMetadata(
        name="Волгоградская область",
        iso3166_2="RU-VGG",
        aliases=("Волгоградская обл.", "Volgograd Oblast"),
    ),
    "Ростовская область": RegionMetadata(
        name="Ростовская область",
        iso3166_2="RU-ROS",
        aliases=("Ростовская обл.", "Rostov Oblast"),
    ),
    "Краснодарский край": RegionMetadata(
        name="Краснодарский край",
        iso3166_2="RU-KDA",
        aliases=("Кубань", "Krasnodar Krai"),
    ),
    "Республика Адыгея": RegionMetadata(
        name="Республика Адыгея",
        iso3166_2="RU-AD",
        aliases=("Адыгея", "Adygea"),
    ),
    "Республика Крым": RegionMetadata(
        name="Республика Крым",
        iso3166_2="RU-CR",
        aliases=("Крым", "Crimea"),
    ),
    "Севастополь": RegionMetadata(
        name="Севастополь",
        iso3166_2="RU-SEV",
        aliases=("Sevastopol",),
    ),
    "Херсонская область": RegionMetadata(
        name="Херсонская область",
        aliases=("Херсонская обл.", "Kherson Oblast"),
    ),
    "Запорожская область": RegionMetadata(
        name="Запорожская область",
        aliases=("Запорожская обл.", "Zaporizhzhia Oblast"),
    ),
    "Донецкая Народная Республика": RegionMetadata(
        name="Донецкая Народная Республика",
        aliases=("ДНР", "Donetsk People's Republic"),
    ),
    "Луганская Народная Республика": RegionMetadata(
        name="Луганская Народная Республика",
        aliases=("ЛНР", "Luhansk People's Republic"),
    ),
    "Республика Калмыкия": RegionMetadata(
        name="Республика Калмыкия",
        iso3166_2="RU-KL",
        aliases=("Калмыкия", "Kalmykia"),
    ),
    "Ставропольский край": RegionMetadata(
        name="Ставропольский край",
        iso3166_2="RU-STA",
        aliases=("Stavropol Krai",),
    ),
    "Карачаево-Черкесская Республика": RegionMetadata(
        name="Карачаево-Черкесская Республика",
        iso3166_2="RU-KC",
        aliases=("Карачаево-Черкесия", "Karachay-Cherkessia"),
    ),
    "Кабардино-Балкарская Республика": RegionMetadata(
        name="Кабардино-Балкарская Республика",
        iso3166_2="RU-KB",
        aliases=("Кабардино-Балкария", "Kabardino-Balkaria"),
    ),
    "Республика Северная Осетия — Алания": RegionMetadata(
        name="Республика Северная Осетия — Алания",
        iso3166_2="RU-SE",
        aliases=("Северная Осетия", "North Ossetia-Alania"),
    ),
    "Республика Ингушетия": RegionMetadata(
        name="Республика Ингушетия",
        iso3166_2="RU-IN",
        aliases=("Ингушетия", "Ingushetia"),
    ),
    "Чеченская Республика": RegionMetadata(
        name="Чеченская Республика",
        iso3166_2="RU-CE",
        aliases=("Чечня", "Chechnya"),
    ),
    "Республика Дагестан": RegionMetadata(
        name="Республика Дагестан",
        iso3166_2="RU-DA",
        aliases=("Дагестан", "Dagestan"),
    ),
    "Астраханская область": RegionMetadata(
        name="Астраханская область",
        iso3166_2="RU-AST",
        aliases=("Астраханская обл.", "Astrakhan Oblast"),
    ),
    "Кировская область": RegionMetadata(
        name="Кировская область",
        iso3166_2="RU-KIR",
        aliases=("Кировская обл.", "Kirov Oblast"),
    ),
    "Республика Марий Эл": RegionMetadata(
        name="Республика Марий Эл",
        iso3166_2="RU-ME",
        aliases=("Марий Эл", "Mari El"),
    ),
    "Чувашская Республика": RegionMetadata(
        name="Чувашская Республика",
        iso3166_2="RU-CU",
        aliases=("Чувашия", "Chuvashia"),
    ),
    "Ульяновская область": RegionMetadata(
        name="Ульяновская область",
        iso3166_2="RU-ULY",
        aliases=("Ульяновская обл.", "Ulyanovsk Oblast"),
    ),
    "Самарская область": RegionMetadata(
        name="Самарская область",
        iso3166_2="RU-SAM",
        aliases=("Самарская обл.", "Samara Oblast"),
    ),
    "Республика Татарстан": RegionMetadata(
        name="Республика Татарстан",
        iso3166_2="RU-TA",
        aliases=("Татарстан", "Tatarstan"),
    ),
    "Удмуртская Республика": RegionMetadata(
        name="Удмуртская Республика",
        iso3166_2="RU-UD",
        aliases=("Удмуртия", "Udmurtia"),
    ),
    "Республика Коми": RegionMetadata(
        name="Республика Коми",
        iso3166_2="RU-KO",
        aliases=("Коми", "Komi Republic"),
    ),
    "Пермский край": RegionMetadata(
        name="Пермский край",
        iso3166_2="RU-PER",
        aliases=("Perm Krai",),
    ),
    "Республика Башкортостан": RegionMetadata(
        name="Республика Башкортостан",
        iso3166_2="RU-BA",
        aliases=("Башкортостан", "Bashkortostan"),
    ),
    "Оренбургская область": RegionMetadata(
        name="Оренбургская область",
        iso3166_2="RU-ORE",
        aliases=("Оренбургская обл.", "Orenburg Oblast"),
    ),
    "Свердловская область": RegionMetadata(
        name="Свердловская область",
        iso3166_2="RU-SVE",
        aliases=("Свердловская обл.", "Sverdlovsk Oblast"),
    ),
    "Челябинская область": RegionMetadata(
        name="Челябинская область",
        iso3166_2="RU-CHE",
        aliases=("Челябинская обл.", "Chelyabinsk Oblast"),
    ),
    "Курганская область": RegionMetadata(
        name="Курганская область",
        iso3166_2="RU-KGN",
        aliases=("Курганская обл.", "Kurgan Oblast"),
    ),
    "Ханты-Мансийский автономный округ — Югра": RegionMetadata(
        name="Ханты-Мансийский автономный округ — Югра",
        iso3166_2="RU-KHM",
        aliases=("ХМАО", "Югра", "Khanty-Mansi Autonomous Okrug"),
    ),
    "Ямало-Ненецкий автономный округ": RegionMetadata(
        name="Ямало-Ненецкий автономный округ",
        iso3166_2="RU-YAN",
        aliases=("ЯНАО", "Yamalo-Nenets Autonomous Okrug"),
    ),
    "Тюменская область": RegionMetadata(
        name="Тюменская область",
        iso3166_2="RU-TYU",
        aliases=("Тюменская обл.", "Tyumen Oblast"),
    ),
    "Омская область": RegionMetadata(
        name="Омская область",
        iso3166_2="RU-OMS",
        aliases=("Омская обл.", "Omsk Oblast"),
    ),
    "Новосибирская область": RegionMetadata(
        name="Новосибирская область",
        iso3166_2="RU-NVS",
        aliases=("Новосибирская обл.", "Novosibirsk Oblast"),
    ),
    "Алтайский край": RegionMetadata(
        name="Алтайский край",
        iso3166_2="RU-ALT",
        aliases=("Altai Krai",),
    ),
    "Республика Алтай": RegionMetadata(
        name="Республика Алтай",
        iso3166_2="RU-AL",
        aliases=("Алтай", "Altai Republic"),
    ),
    "Томская область": RegionMetadata(
        name="Томская область",
        iso3166_2="RU-TOM",
        aliases=("Томская обл.", "Tomsk Oblast"),
    ),
    "Кемеровская область — Кузбасс": RegionMetadata(
        name="Кемеровская область — Кузбасс",
        iso3166_2="RU-KEM",
        aliases=("Кемеровская область", "Кузбасс", "Kemerovo Oblast"),
    ),
    "Республика Хакасия": RegionMetadata(
        name="Республика Хакасия",
        iso3166_2="RU-KK",
        aliases=("Хакасия", "Khakassia"),
    ),
    "Красноярский край": RegionMetadata(
        name="Красноярский край",
        iso3166_2="RU-KYA",
        aliases=("Krasnoyarsk Krai",),
    ),
    "Республика Тыва": RegionMetadata(
        name="Республика Тыва",
        iso3166_2="RU-TY",
        aliases=("Тыва", "Тува", "Tuva"),
    ),
    "Иркутская область": RegionMetadata(
        name="Иркутская область",
        iso3166_2="RU-IRK",
        aliases=("Иркутская обл.", "Irkutsk Oblast"),
    ),
    "Республика Бурятия": RegionMetadata(
        name="Республика Бурятия",
        iso3166_2="RU-BU",
        aliases=("Бурятия", "Buryatia"),
    ),
    "Забайкальский край": RegionMetadata(
        name="Забайкальский край",
        iso3166_2="RU-ZAB",
        aliases=("Zabaykalsky Krai",),
    ),
    "Республика Саха (Якутия)": RegionMetadata(
        name="Республика Саха (Якутия)",
        iso3166_2="RU-SA",
        aliases=("Якутия", "Саха", "Sakha Republic", "Yakutia"),
    ),
    "Амурская область": RegionMetadata(
        name="Амурская область",
        iso3166_2="RU-AMU",
        aliases=("Амурская обл.", "Amur Oblast"),
    ),
    "Еврейская автономная область": RegionMetadata(
        name="Еврейская автономная область",
        iso3166_2="RU-YEV",
        aliases=("ЕАО", "Jewish Autonomous Oblast"),
    ),
    "Хабаровский край": RegionMetadata(
        name="Хабаровский край",
        iso3166_2="RU-KHA",
        aliases=("Khabarovsk Krai",),
    ),
    "Приморский край": RegionMetadata(
        name="Приморский край",
        iso3166_2="RU-PRI",
        aliases=("Приморье", "Primorsky Krai"),
    ),
    "Магаданская область": RegionMetadata(
        name="Магаданская область",
        iso3166_2="RU-MAG",
        aliases=("Магаданская обл.", "Magadan Oblast"),
    ),
    "Чукотский автономный округ": RegionMetadata(
        name="Чукотский автономный округ",
        iso3166_2="RU-CHU",
        aliases=("Чукотка", "Chukotka Autonomous Okrug"),
    ),
    "Камчатский край": RegionMetadata(
        name="Камчатский край",
        iso3166_2="RU-KAM",
        aliases=("Камчатка", "Kamchatka Krai"),
    ),
    "Сахалинская область": RegionMetadata(
        name="Сахалинская область",
        iso3166_2="RU-SAK",
        aliases=("Сахалинская обл.", "Sakhalin Oblast"),
    ),
}
