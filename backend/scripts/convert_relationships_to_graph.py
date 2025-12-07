import pandas as pd
import leidenalg as la
import igraph as ig

import matplotlib.cm as cm
import matplotlib.colors as mcolors
import json

# df = pl.read_parquet("data/yandex5_podcast/create_final_relationships.parquet")
pdf = pd.read_parquet("data/output_gazeta_threshold/create_final_relationships.parquet")

pd.options.display.max_columns = 20

linksExplanations = {
    f"{row['source']}_{row['target']}": row["description"] for _, row in pdf.iterrows()
}


pdf = pdf[["source", "target", "weight"]]

vertices = pd.Index(pd.concat([pdf["source"], pdf["target"]]).unique())
name_to_idx = {name: i for i, name in enumerate(vertices)}

edges_idx = [
    (name_to_idx[s], name_to_idx[t]) for s, t in zip(pdf["source"], pdf["target"])
]

g = ig.Graph(n=len(vertices), edges=edges_idx)
g.vs["name"] = list(vertices)
g.es["weight"] = pdf["weight"].astype(float).tolist()


partition = la.find_partition(
    g,
    la.CPMVertexPartition,
    weights=g.es["weight"],
    resolution_parameter=0.5,
)

membership = partition.membership
g.vs["community"] = membership

cmap = cm.get_cmap("tab20", len(set(membership)))
community_colors = [mcolors.to_hex(cmap(i)) for i in range(len(set(membership)))]


layout = g.layout("fruchterman_reingold")
coords = layout.coords


# nodes_df = pd.read_parquet("data/yandex5_podcast/create_final_nodes.parquet")
nodes_df = pd.read_parquet("data/output_gazeta_threshold/create_final_nodes.parquet")

nodesSizes = {row["title"]: row["size"] for _, row in nodes_df.iterrows()}
nodesText = {
    row["title"]: f"TYPE: {row['type']}\n\n\n {row['description']}"
    for _, row in nodes_df.iterrows()
}


nodes = []
for i, v in enumerate(g.vs):
    community_id = v["community"]
    color = community_colors[community_id % len(community_colors)]
    nodes.append(
        {
            "id": i,
            "data": {
                "texts": [{"id": i, "text": nodesText.get(v["name"], "")}],
                "color": color,
                "size": 2,
            },
            "name": v["name"],
            "vx": 0,
            "vy": 0,
            "x": coords[i][0] * 20,
            "y": coords[i][1] * 20,
        }
    )

links = []
for idx, e in enumerate(g.es):
    source_name = g.vs[e.source]["name"]
    target_name = g.vs[e.target]["name"]
    links.append(
        {
            "source": e.source,
            "target": e.target,
            "data": {
                "id": idx,
                "explanation": linksExplanations.get(
                    f"{source_name}_{target_name}", ""
                ),
                "color": "#000000",
            },
        }
    )

graph_json = {"nodes": nodes, "links": links}

with open("graph.json", "w", encoding="utf-8") as f:
    json.dump(graph_json, f, ensure_ascii=False, indent=4)


# reports_df = pd.read_parquet(
#     "data/yandex5_podcast/create_final_community_reports.parquet"
# )
reports_df = pd.read_parquet(
    "data/output_gazeta_threshold/create_final_community_reports.parquet"
)

data = []
for ind, row in reports_df.iterrows():
    print(row)
    data.append({"pid": ind, "text": row["full_content"]})


with open("rep.json", "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
