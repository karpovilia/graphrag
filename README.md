### Добавление нового графа

1. Добавить в файле `import-map.json` информацию о графе: название для отображения в меню и хедере (name), идентификатор для урла (id) и путь к папке в которой будет статика с конкретным графом (path)
2. Положить json с графом названный graph.json в папку указанную в path в импорт мапе. Например если путь `static/uzb_pos`, то граф положить по пути `static/uzb_pos/graph.json`
3. Положить все текста для ссылок по тому же пути с произвольным названием (random_name.json). **Генерация ссылки** для текста выглядит следующим образом: `/text/{graph_id}/{file_name}/{paragraph_id}`, где `graph_id` - это идентификатор из импорт мапы, `file_name` - это название файла с текстом, `paragraph_id` - это идентификатор параграфа в тексте.

Текст принимается вида:

```json
[
  {
    "pid": 1,
    "text": "Lorem Ipsum is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry's standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to make a type specimen book. It has survived not only five centuries, but also the leap into electronic typesetting, remaining essentially unchanged. It was popularised in the 1960s with the release of Letraset sheets containing Lorem Ipsum passages, and more recently with desktop publishing software like Aldus PageMaker including versions of Lorem Ipsum."
  },
  {
    "pid": 2,
    "text": "Lorem Ipsum is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry's standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to make a type specimen book. It has survived not only five centuries, but also the leap into electronic typesetting, remaining essentially unchanged. It was popularised in the 1960s with the release of Letraset sheets containing Lorem Ipsum passages, and more recently with desktop publishing software like Aldus PageMaker including versions of Lorem Ipsum."
  }
]
```

[Dev стенд](http://country.aps/)
