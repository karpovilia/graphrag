CREATE TABLE prompt_histories (
    id SERIAL PRIMARY KEY NOT NULL,
    prompt TEXT,
    graph TEXT,
    response TEXT
);

CREATE TABLE prompt_selected_nodes (
    id SERIAL PRIMARY KEY NOT NULL,
    prompt_id SERIAL REFERENCES prompt_histories(id),
    node TEXT
)
