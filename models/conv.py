import torch
import torch.nn.functional as F

from utils.config import cfg
from ogb.graphproppred.mol_encoder import AtomEncoder
from torch_geometric.nn.conv import GINConv, GCNConv

class GNN_node(torch.nn.Module):
    def __init__(self):
        super(GNN_node, self).__init__()

        self.num_layer = cfg.gnn.num_layers
        self.dropout = cfg.gnn.dropout

        self.convs = torch.nn.ModuleList()
        self.batch_norms = torch.nn.ModuleList()

        self.node_encoder = self._get_node_encoder(cfg.gnn.hidden_dim)

        for layer in range(self.num_layer):
            input_dim = cfg.gnn.hidden_dim if cfg.gnn.node_encoder == 'Atom' or layer > 0 else cfg.gnn.input_dim

            self.convs.append(self._get_gin_layer(input_dim, cfg.gnn.hidden_dim))

            self.batch_norms.append(torch.nn.BatchNorm1d(cfg.gnn.hidden_dim))

    def forward(self, batched_data):
            x = self.node_encoder(batched_data.x) if self.node_encoder is not None else batched_data.x.float()
            batch = batched_data.batch

            is_cgp = cfg.transform.name == "CGP"
            if is_cgp:
                # Expander the embeddings with the virtual nodes
                # Here, we just overwrite the virtual nodes to zero, but more to be added (todo)
                x_embeddings = torch.zeros((x.shape[0], x.shape[1]), device=x.device)
                x_embeddings[~batched_data.virtual_node_mask] = x[~batched_data.virtual_node_mask]

                h_list = [x_embeddings]
            else:
                h_list = [x.float()]

            h_list = [x]

            def get_edge_index(layer: int):
                """Helper function to determine which edge index to use."""

                if (cfg.transform.name in ["EGP", "CGP"] and layer % 2 == 1) or \
                    (cfg.transform.name == "FA" and layer == self.num_layer - 1):
                    return batched_data.rewiring_edge_index

                return batched_data.edge_index

            for layer in range(self.num_layer):
                edge_index = get_edge_index(layer)

                h = self.convs[layer](h_list[layer], edge_index)
                h = self.batch_norms[layer](h)

                if layer == self.num_layer - 1:
                    h = F.dropout(h, self.dropout)
                else:
                    h = F.dropout(F.relu(h), self.dropout)

                h_list.append(h)
                
            node_representation = h_list[-1]
            
            if is_cgp:
                node_representation = node_representation[~batched_data.virtual_node_mask]
                batch = batch[~batched_data.virtual_node_mask]

            return node_representation, batch

    def _get_node_encoder(self, hidden_dim):
        if cfg.gnn.node_encoder is None:
            return None
        
        node_encoder = cfg.gnn.node_encoder.lower()

        if node_encoder == 'atom':
            return AtomEncoder(hidden_dim)
        elif node_encoder == 'uniform':
            return torch.nn.Embedding(1, hidden_dim)
        else:
            raise ValueError(f'Node encoder does not exist {node_encoder}')

    def _get_layer(self, input_dim, hidden_dim):
        gnn_type = cfg.gnn.layer_type.lower()
        if gnn_type == 'gin':
            return self._get_gin_layer(input_dim, hidden_dim)
        else:
            return GCNConv(input_dim, hidden_dim)

    def _get_gin_layer(self, input_dim, hidden_dim):
        emb_dim = 2*hidden_dim if cfg.dataset.format == 'OGB' else hidden_dim

        mlp = torch.nn.Sequential(
            torch.nn.Linear(input_dim, emb_dim),
            torch.nn.BatchNorm1d(emb_dim),
            torch.nn.ReLU(),
            torch.nn.Linear(emb_dim, cfg.gnn.hidden_dim)
        )

        return GINConv(mlp)

if __name__ == "__main__":
    GNN_node()
