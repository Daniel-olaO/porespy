import importlib
import collections
import numpy as np
import openpnm as op
from porespy.filters import trim_nonpercolating_paths
from loguru import logger


def tortuosity(im, axis, return_im=False, **kwargs):
    r"""
    Calculates tortuosity of given image in specified direction

    Parameters
    ----------
    im : ndarray
        The binary image to analyze with ``True`` indicating phase of interest
    axis : int
        The axis along which to apply boundary conditions
    return_im : boolean
        If ``True`` then the resulting tuple contains a copy of the input
        image with the concentration profile.

    Returns
    -------
    results : tuple
        A named-tuple containing:
          - ``tortuosity``: calculated using the ``effective_porosity``
            as :math:`\tau = \frac{D_{AB}}{D_{eff}} \cdot \varepsilon`.
          - ``effective_porosity``: of the image after applying
            ``trim_nonpercolating_paths``. This removes disconnected
            voxels which cause singular matrices.
          - ``original_porosity``: of the image as given
          - ``formation_factor``: found as :math:`D_{AB}/D_{eff}`.
          - ``image``: containing the concentration values from the
            simulation. This is only returned if ``return_im`` is
            ``True``.

    """
    if axis > (im.ndim - 1):
        raise Exception("Axis argument is too high")
    # Obtain original porosity
    eps0 = im.sum() / im.size
    # Removing floating pores
    im = trim_nonpercolating_paths(im, inlet_axis=axis, outlet_axis=axis)
    # Porosity is changed because of trimmimg floating pores
    eps = im.sum() / im.size
    if eps < eps0:  # pragma: no cover
        logger.warning(f'True porosity is {eps:.2f}, filled {eps0 - eps:.2f}'
                       ' volume fraction of the image for it to percolate.')
    # Cubic network generation
    net = op.network.CubicTemplate(template=im, spacing=1)
    # Adding phase
    water = op.phases.Water(network=net)
    water['throat.diffusive_conductance'] = 1  # dummy value
    # Running Fickian Diffusion
    fd = op.algorithms.FickianDiffusion(network=net, phase=water)
    # Choosing axis of concentration gradient
    inlets = net['pore.coords'][:, axis] <= 1
    outlets = net['pore.coords'][:, axis] >= im.shape[axis]-1
    # Boundary conditions on concentration
    C_in = 1.0
    C_out = 0.0
    fd.set_value_BC(pores=inlets, values=C_in)
    fd.set_value_BC(pores=outlets, values=C_out)
    # Use specified solver if given
    if 'solver_family' in kwargs.keys():
        fd.settings.update(kwargs)
    else:
        fd.settings['solver_family'] = 'scipy'
        fd.settings['solver_type'] = 'cg'
        if importlib.util.find_spec("pyamg") is None:
            fd.settings['solver_family'] = 'pyamg'
    fd.run()
    # Calculating molar flow rate, effective diffusivity and tortuosity
    rate_out = fd.rate(pores=outlets)[0]
    rate_in = fd.rate(pores=inlets)[0]
    if not np.allclose(-rate_out, rate_in):
        raise Exception('Something went wrong, inlet and outlet rate do not match')
    delta_C = C_in - C_out
    L = im.shape[axis]
    A = np.prod(im.shape) / L
    N_A = A / L * delta_C
    Deff = rate_in / N_A
    tau = eps / Deff
    result = collections.namedtuple(
        'tortuosity_result',
        ['tortuosity',
         'effective_porosity',
         'original_porosity',
         'formation_factor',
         'image'])
    result.tortuosity = tau
    result.formation_factor = 1 / Deff
    result.original_porosity = eps0
    result.effective_porosity = eps
    if return_im:
        conc = np.zeros([im.size, ], dtype=float)
        conc[net['pore.template_indices']] = fd['pore.concentration']
        conc = np.reshape(conc, newshape=im.shape)
        result.image = conc
    else:
        result.image = None
    return result
