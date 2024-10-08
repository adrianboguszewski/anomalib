"""Random Sparse Projector.

Sparse Random Projection using PyTorch Operations
"""

# Copyright (C) 2022-2024 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import numpy as np
import torch
from sklearn.utils.random import sample_without_replacement


class NotFittedError(ValueError, AttributeError):
    """Raise Exception if estimator is used before fitting."""


class SparseRandomProjection:
    """Sparse Random Projection using PyTorch operations.

    Args:
        eps (float, optional): Minimum distortion rate parameter for calculating
            Johnson-Lindenstrauss minimum dimensions.
            Defaults to ``0.1``.
        random_state (int | None, optional): Uses the seed to set the random
            state for sample_without_replacement function.
            Defaults to ``None``.

    Example:
        To fit and transform the embedding tensor, use the following code:

        .. code-block:: python

            import torch
            from anomalib.models.components import SparseRandomProjection

            sparse_embedding = torch.rand(1000, 5).cuda()
            model = SparseRandomProjection(eps=0.1)

        Fit the model and transform the embedding tensor:

        .. code-block:: python

            model.fit(sparse_embedding)
            projected_embedding = model.transform(sparse_embedding)

            print(projected_embedding.shape)
            # Output: torch.Size([1000, 5920])
    """

    def __init__(self, eps: float = 0.1, random_state: int | None = None) -> None:
        self.n_components: int
        self.sparse_random_matrix: torch.Tensor
        self.eps = eps
        self.random_state = random_state

    def _sparse_random_matrix(self, n_features: int) -> torch.Tensor:
        """Random sparse matrix. Based on https://web.stanford.edu/~hastie/Papers/Ping/KDD06_rp.pdf.

        Args:
            n_features (int): Dimentionality of the original source space

        Returns:
            Tensor: Sparse matrix of shape (n_components, n_features).
                The generated Gaussian random matrix is in CSR (compressed sparse row)
                format.
        """
        # Density 'auto'. Factorize density
        density = 1 / np.sqrt(n_features)

        if density == 1:
            # skip index generation if totally dense
            binomial = torch.distributions.Binomial(total_count=1, probs=0.5)
            components = binomial.sample((self.n_components, n_features)) * 2 - 1
            components = 1 / np.sqrt(self.n_components) * components

        else:
            # Sparse matrix is not being generated here as it is stored as dense anyways
            components = torch.zeros((self.n_components, n_features), dtype=torch.float32)
            for i in range(self.n_components):
                # find the indices of the non-zero components for row i
                nnz_idx = torch.distributions.Binomial(total_count=n_features, probs=density).sample()
                # get nnz_idx column indices
                # pylint: disable=not-callable
                c_idx = torch.tensor(
                    sample_without_replacement(
                        n_population=n_features,
                        n_samples=nnz_idx,
                        random_state=self.random_state,
                    ),
                    dtype=torch.int32,
                )
                data = torch.distributions.Binomial(total_count=1, probs=0.5).sample(sample_shape=c_idx.size()) * 2 - 1
                # assign data to only those columns
                components[i, c_idx] = data

            components *= np.sqrt(1 / density) / np.sqrt(self.n_components)

        return components

    @staticmethod
    def _johnson_lindenstrauss_min_dim(n_samples: int, eps: float = 0.1) -> int | np.integer:
        """Find a 'safe' number of components to randomly project to.

        Ref eqn 2.1 https://cseweb.ucsd.edu/~dasgupta/papers/jl.pdf

        Args:
            n_samples (int): Number of samples used to compute safe components
            eps (float, optional): Minimum distortion rate. Defaults to 0.1.
        """
        denominator = (eps**2 / 2) - (eps**3 / 3)
        return (4 * np.log(n_samples) / denominator).astype(np.int64)

    def fit(self, embedding: torch.Tensor) -> "SparseRandomProjection":
        """Generate sparse matrix from the embedding tensor.

        Args:
            embedding (torch.Tensor): embedding tensor for generating embedding

        Returns:
            (SparseRandomProjection): Return self to be used as

            >>> model = SparseRandomProjection()
            >>> model = model.fit()
        """
        n_samples, n_features = embedding.shape
        device = embedding.device

        self.n_components = self._johnson_lindenstrauss_min_dim(n_samples=n_samples, eps=self.eps)

        # Generate projection matrix
        # torch can't multiply directly on sparse matrix and moving sparse matrix to cuda throws error
        # (Could not run 'aten::empty_strided' with arguments from the 'SparseCsrCUDA' backend)
        # hence sparse matrix is stored as a dense matrix on the device
        self.sparse_random_matrix = self._sparse_random_matrix(n_features=n_features).to(device)

        return self

    def transform(self, embedding: torch.Tensor) -> torch.Tensor:
        """Project the data by using matrix product with the random matrix.

        Args:
            embedding (torch.Tensor): Embedding of shape (n_samples, n_features)
                The input data to project into a smaller dimensional space

        Returns:
            projected_embedding (torch.Tensor): Sparse matrix of shape
                (n_samples, n_components) Projected array.

        Example:
            >>> projected_embedding = model.transform(embedding)
            >>> projected_embedding.shape
            torch.Size([1000, 5920])
        """
        if self.sparse_random_matrix is None:
            msg = "`fit()` has not been called on SparseRandomProjection yet."
            raise NotFittedError(msg)

        return embedding @ self.sparse_random_matrix.T.float()
