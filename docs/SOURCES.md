# Источники и атрибуция

Дата проверки и загрузки официального снимка: 27.10.2026.

| Источник | Для чего используется |
|---|---|
| [Nobel API: laureates](https://api.nobelprize.org/2.1/laureates) | Все лауреаты, биографические события, премии, аффилиации, проживания, ссылки и языковые версии |
| [Nobel API: nobelPrizes](https://api.nobelprize.org/2.1/nobelPrizes) | Все записи премий, получатели, суммы, неприсуждение, сверка полноты |
| [Developer zone](https://www.nobelprize.org/about/developer-zone-2/) | Официальное описание открытых данных |
| [Getting started](https://nobelprize.readme.io/reference/getting-started) | Область данных API, аффилиации при награждении |
| [Условия API](https://www.nobelprize.org/about/terms-of-use-for-api-nobelprize-org-and-data-nobelprize-org/) | Условия доступа и использования данных API; ссылки также сохранены в `meta` ответов |
| [Wikidata / wbgetentities](https://www.wikidata.org/w/api.php?action=help&modules=wbgetentities) | Необязательное дополнительное обогащение |
| [MediaWiki API etiquette](https://www.mediawiki.org/wiki/API:Etiquette) | Последовательные запросы, `maxlag`, User-Agent |
| [Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy) | Идентификация приложения и контакт владельца |
| [Plotly world topology](https://cdn.plot.ly/world_110m.json) | Локальная картографическая подложка `static/world_110m.json`, Natural Earth / Plotly |
| [Natural Earth terms](https://www.naturalearthdata.com/about/terms-of-use/) | Условия использования картографических данных |
| [Streamlit deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app) | Размещение сайта |
| [Streamlit static files](https://docs.streamlit.io/develop/concepts/configuration/serving-static-files) | Локальная подложка карт |
| [Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest) | Проверка интерфейса |
| [FastAPI query parameters](https://fastapi.tiangolo.com/tutorial/query-params/) | Параметры HTTP-сервера |
| [GitHub: отключение расписаний](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows) | Ограничение активности публичного репозитория |

Нобелевские данные получены непосредственно от Nobel Prize Outreach. Проект не аффилирован с Нобелевским фондом. В интерфейсе есть ссылка на источник, а в базе сохранены исходные `terms`, `license`, `disclaimer` из ответов API. Пользовательские тексты сайта не заменяют условия источника.

Полные биографические статьи, фотографии и логотипы NobelPrize.org не скачиваются. API не является лицензией на автоматическое копирование всего сайта. Карточки оформлены средствами интерфейса; мотивировки отображаются как официальные данные, со ссылками. Для последующего добавления фотографий нужно отдельно сохранять авторство, лицензию конкретного изображения и страницу источника.

Оригинальные JSON сохраняют данные без изменения; аналитический слой очищает HTML-разметку текста, переводит категории интерфейса на русский, рассчитывает возраст и производные показатели. Все добавления Wikidata при запуске обогащения отделены от официальных фактов и сохраняют происхождение.
