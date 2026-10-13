
from __future__ import annotations

import torch
import torch.nn as nn
from transformers import Qwen3Model


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        dtype = x.dtype
        x = x.float()
        x = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return (self.weight * x).to(dtype)


class CandidateSetEncoder(nn.Module):
    

    def __init__(self, d_model: int = 256, nhead: int = 4, num_layers: int = 2,
                 dropout: float = 0.0):
        super().__init__()
        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=4 * d_model,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(layer, num_layers=num_layers)

    def forward(self, x: torch.Tensor, cand_mask: torch.Tensor) -> torch.Tensor:
        
        
        return self.encoder(x, src_key_padding_mask=~cand_mask)


class ScalarScorer(nn.Module):
    

    def __init__(self, in_dim: int = 1024, hidden: int = 256):
        super().__init__()
        self.norm = RMSNorm(in_dim)
        self.fc1 = nn.Linear(in_dim, hidden)
        self.act = nn.SiLU()
        self.fc2 = nn.Linear(hidden, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(self.act(self.fc1(self.norm(x)))).squeeze(-1)


class PathEncoder(nn.Module):
    

    def __init__(self, backbone: Qwen3Model):
        super().__init__()
        self.backbone = backbone

    def forward(self, batch: dict) -> torch.Tensor:
        out = self.backbone(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            use_cache=False,
        )
        hs = out.last_hidden_state  
        P = hs.size(0)
        pos = batch["cand_end_pos"]
        h = hs[torch.arange(P, device=hs.device), pos]  
        Bq, Cmax = batch["cand_mask"].shape
        cand_vecs = hs.new_zeros(Bq, Cmax, hs.size(-1))
        cand_vecs[batch["q_index"], batch["cand_index"]] = h
        return cand_vecs


class TreeEncoder(nn.Module):
    

    def __init__(self, backbone: Qwen3Model):
        super().__init__()
        self.backbone = backbone

    def forward(self, batch: dict) -> torch.Tensor:
        raise NotImplementedError(
            "prefix-tree shared-prefix encoding not implemented yet; "
            "use encoder_impl='path'"
        )


class AgentJevModel(nn.Module):
    def __init__(
        self,
        backbone_path: str,
        set_dim: int = 256,
        set_layers: int = 2,
        set_heads: int = 4,
        encoder_impl: str = "path",
        dtype: torch.dtype = torch.float32,
    ):
        super().__init__()
        backbone = Qwen3Model.from_pretrained(backbone_path, torch_dtype=dtype)
        hidden = backbone.config.hidden_size
        self.hidden_size = hidden

        if encoder_impl == "path":
            self.path_encoder = PathEncoder(backbone)
        elif encoder_impl == "tree":
            self.path_encoder = TreeEncoder(backbone)
        else:
            raise ValueError(f"unknown encoder_impl: {encoder_impl}")

        self.proj_in = nn.Linear(hidden, set_dim)
        self.set_encoder = CandidateSetEncoder(set_dim, set_heads, set_layers)
        self.proj_out = nn.Linear(set_dim, hidden)
        self.scorer = ScalarScorer(hidden, set_dim)

    
    def backbone_named_parameters(self):
        return self.path_encoder.backbone.named_parameters()

    def head_named_parameters(self):
        for module in (self.proj_in, self.set_encoder, self.proj_out, self.scorer):
            yield from module.named_parameters()

    
    def encode_candidates(self, batch: dict) -> torch.Tensor:
        return self.path_encoder(batch)

    def _score(self, cand_vecs: torch.Tensor, cand_mask: torch.Tensor) -> torch.Tensor:
        x = self.proj_in(cand_vecs)
        x = x * cand_mask.unsqueeze(-1).to(x.dtype)
        enc = self.set_encoder(x, cand_mask)
        rep = cand_vecs + self.proj_out(enc)
        logits = self.scorer(rep)  
        return logits.masked_fill(~cand_mask, -1e4)

    def forward(self, batch: dict, perm_reg: bool = False) -> dict:
        cand_mask = batch["cand_mask"]
        cand_vecs = self.encode_candidates(batch)
        logits = self._score(cand_vecs, cand_mask)

        out = {"logits": logits, "cand_mask": cand_mask}

        if perm_reg:
            
            
            
            
            Bq, Cmax = cand_mask.shape
            device = cand_vecs.device
            perm = torch.arange(Cmax, device=device).unsqueeze(0).repeat(Bq, 1)
            for q in range(Bq):
                c = int(cand_mask[q].sum())
                if c > 1:
                    perm[q, :c] = torch.randperm(c, device=device)
            idx_h = perm.unsqueeze(-1).expand(-1, -1, cand_vecs.size(-1))
            vecs_p = cand_vecs.gather(1, idx_h)
            mask_p = cand_mask.gather(1, perm)
            
            
            logits_p = self._score(vecs_p, mask_p)
            inv_perm = torch.argsort(perm, dim=1)
            out["logits_perm"] = logits_p.gather(1, inv_perm)
            out["cand_mask"] = cand_mask

        return out
