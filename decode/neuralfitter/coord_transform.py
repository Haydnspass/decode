import torch

from ..generic import utils


class Offset2Coordinate:
    """
    Convert sub-pixel pointers to absolute coordinates.
    """

    def __init__(self, xextent: tuple, yextent: tuple, img_shape: tuple):
        """

        Args:
            xextent (tuple): extent in x
            yextent (tuple): extent in y
            img_shape (tuple): image shape
        """

        *_, bin_ctr_x, bin_ctr_y = utils.frame_grid(img_shape, xextent, yextent)

        xv, yv = torch.meshgrid([bin_ctr_x, bin_ctr_y])
        self._x_mesh = xv.unsqueeze(0)
        self._y_mesh = yv.unsqueeze(0)

    def _subpx_to_absolute(self, x_offset, y_offset):
        """
        Convert subpixel pointers to absolute coordinates. Actual implementation

        Args:
            x_offset: N x H x W
            y_offset: N x H x W

        Returns:

        """
        batch_size = x_offset.size(0)
        x_coord = self._x_mesh.repeat(batch_size, 1, 1).to(x_offset.device) + x_offset
        y_coord = self._y_mesh.repeat(batch_size, 1, 1).to(y_offset.device) + y_offset
        return x_coord, y_coord

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward frames through post-processor.

        Args:
            x (torch.Tensor): features to be converted. Expecting x/y coordinates in channel index 2, 3.
             expected shape :math:`(N, C, H, W)`

        """

        if x.dim() != 4:
            raise ValueError("Wrong dimensionality. Needs to be N x C x H x W.")

        # convert the channel values to coordinates
        x_coord, y_coord = self._subpx_to_absolute(x[:, 2], x[:, 3])

        output_converted = x.clone()
        output_converted[:, 2] = x_coord
        output_converted[:, 3] = y_coord

        return output_converted
