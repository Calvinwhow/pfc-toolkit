# Tools to perform Lesion Network Mapping with the Precomputed Connectome
# William Drew 2021 (wdrew@bwh.harvard.edu)

import os, time
import numpy as np
from numba import jit
from nilearn import image
from pfctoolkit import tools, datasets

def process_chunk(chunk, rois, config):
    """Compute chunk contribution to FC maps for a given list of ROIs.

    Parameters
    ----------
    chunk : int
        Index of chunk to be processed.
    rois : list of str
        List of ROI paths to be processed.
    config : pfctoolkit.config.Config
        Configuration of the precomputed connectome.

    Returns
    -------
    contributions : dict of ndarray
        Dictionary containing contributions to network maps.

    """
    chunk_paths = {
        "avgr": config.get("avgr"),
        "fz": config.get("fz"),
        "t": config.get("t"),
        "combo": config.get("combo")
    }
    brain_masker = tools.NiftiMasker(datasets.get_img(config.get("mask")))
    chunk_masker = tools.NiftiMasker(image.math_img(f"img=={chunk}", 
                                     img=config.get("chunk_idx")))
    brain_weights = np.array([brain_masker.transform(roi) for roi in rois])
    chunk_weights = np.array([chunk_masker.transform(roi) for roi in rois])
    brain_masks = np.array([(weights != 0) for weights in brain_weights])
    chunk_masks = np.array([(weights != 0) for weights in chunk_weights])
    norm_weight = chunk_masker.transform(config.get("norm"))
    std_weight = chunk_masker.transform(config.get("std"))

    norm_chunk_masks, std_chunk_masks = compute_chunk_masks(chunk_weights, 
                                                            norm_weight, 
                                                            std_weight)
    contributions = {}
    for chunk_type in [("avgr", "AvgR"), 
                       ("fz", "AvgR_Fz"), 
                       ("t", "T"), 
                       ("combo", "Combo"),
                      ]:
        start_time = time.time()
        chunk_data = np.load(os.path.join(chunk_paths[chunk_type[0]], 
                                          f"{chunk}_{chunk_type[1]}.npy"))
        end_time = time.time()
        print("--- %s seconds : Load chunk ---" % (end_time - start_time))
        if(chunk_data.shape != (config.get("chunk_size"), 
                                config.get("brain_size"))):
            raise TypeError("Chunk expected to have shape {(config.get('chunk_size'), config.get('brain_size'))} but instead has shape {np.shape(chunk_data)}!")
        if(chunk_type[0] == "combo"):
            numerator = compute_numerator(norm_chunk_masks)
            start_time = time.time()
            for i, roi in enumerate(rois):
                denominator = compute_denominator(brain_weights, chunk_weights, 
                                                  brain_masks, chunk_masks, 
                                                  chunk_data, i)
                contributions[roi]["numerator"] = numerator[i]
                contributions[roi]["denominator"] = denominator
            end_time = time.time()
            print("--- %s seconds : Combo loop ---" % (end_time - start_time))
        else:
            start_time = time.time()
            network_maps = compute_network_maps(std_chunk_masks, chunk_data)
            end_time = time.time()
            print("--- %s seconds : Compute network maps ---" % (end_time - start_time))
            for i, roi in enumerate(rois):
                if(chunk_type[0] == "avgr"):
                    contributions[roi] = {
                        chunk_type[0]: network_maps[i,:],
                    }
                else:
                    contributions[roi][chunk_type[0]] = network_maps[i,:]
    network_weights = compute_network_weights(std_chunk_masks)
    for i, roi in enumerate(rois):
        contributions[roi]["network_weight"] = network_weights[i]
    return contributions

@jit(nopython=True)
def compute_network_weights(std_chunk_masks):
    """Compute network weights.

    Parameters
    ----------
    std_chunk_masks : ndarray
        Chunk-masked ROIs weighted by BOLD standard deviation.

    Returns
    -------
    network_weights : ndarray
        Contribution to total network map weights.
        
    """
    network_weights = np.sum(std_chunk_masks, axis = 1)
    return network_weights

@jit(nopython=True)
def compute_network_maps(std_chunk_masks, chunk_data):
    """Compute network maps.

    Parameters
    ----------
    std_chunk_masks : ndarray
        Chunk-masked ROIs weighted by BOLD standard deviation.
    chunk_data : ndarray
        Chunk data.

    Returns
    -------
    network maps : ndarray
        Network map contributions from chunk.

    """
    network_maps = np.matmul(std_chunk_masks, chunk_data)
    return network_maps

@jit(nopython=True)
def compute_denominator(brain_weights, 
                        chunk_weights, 
                        brain_masks, 
                        chunk_masks, 
                        chunk_data, 
                        i
                        ):
    """Compute denominator contribution.

    Parameters
    ----------
    brain_weights : ndarray
        Brain-masked weighted ROIs.
    chunk_weights : ndarray
        Chunk-masked weighted ROIs.
    brain_masks : ndarray
        Brain-masked unweighted ROIs.
    chunk_masks : ndarray
        Chunk-masked unweighted ROIs.
    chunk_data : ndarray
        Chunk data.
    i : int
        Index of processed ROI.

    Returns
    -------
    denominator : float
        Contribution to denominator.

    """
    chunk_masked = np.multiply(np.reshape(chunk_weights[i][chunk_masks[i]], 
                                          (-1,1)), chunk_data[chunk_masks[i],:])
    brain_masked = np.multiply(brain_weights[i][brain_masks[i]], 
                               chunk_masked[:,brain_masks[i]])
    denominator = np.sum(brain_masked)
    return denominator

@jit(nopython=True)
def compute_numerator(norm_chunk_masks):
    """Compute numerator contribution.

    Parameters
    ----------
    norm_chunk_masks : ndarray
        ROI chunk masks weighted with BOLD norms.

    Returns
    -------
    numerator : float
        Numerator contribution

    """
    numerator = np.sum(norm_chunk_masks, axis = 1)
    return numerator

@jit(nopython=True)
def compute_chunk_masks(chunk_weights, norm_weight, std_weight):
    """Compute weighted chunk masks.

    Parameters
    ----------
    chunk_weights : ndarray
        Chunk-masked weighted ROIs.
    norm_weight : ndarray
        Chunk-masked voxel BOLD norms.
    std_weight : ndarray
        Chunk-masked voxel BOLD standard deviations.

    Returns
    -------
    norm_weighted_chunk_masks : ndarray
        ROI chunk masks weighted with BOLD norms.
    std_weighted_chunk_masks : ndarray
        ROI chunk masks weighted with BOLD standard deviations.

    """
    norm_weighted_chunk_masks = np.multiply(chunk_weights, norm_weight)
    std_weighted_chunk_masks = np.multiply(chunk_weights, std_weight)
    return norm_weighted_chunk_masks,std_weighted_chunk_masks

def consolidate(contribution, atlas):
    """Consolidate chunk contributions into running in-progress FC map atlas.

    Parameters
    ----------
    contribution : dict
        dict containing FC and scaling factor contributions from a chunk.
    atlas : dict
        dict containing in-progress FC maps and scaling factor accumulators.

    Returns
    -------
    atlas : dict
        Updated dict containing in-progress FC maps and scaling factor
        accumulators following consolidation of the contribution.

    """
    for roi in contribution.keys():
        if roi in atlas:
            atlas[roi]["avgr"] += contribution[roi]["avgr"]
            atlas[roi]["fz"] += contribution[roi]["fz"]
            atlas[roi]["t"] += contribution[roi]["t"]
            atlas[roi]["network_weight"] += contribution[roi]["network_weight"]
            atlas[roi]["numerator"] += contribution[roi]["numerator"]
            atlas[roi]["denominator"] += contribution[roi]["denominator"]
        else:
            atlas[roi] = {
                "avgr": contribution[roi]["avgr"],
                "fz": contribution[roi]["fz"],
                "t": contribution[roi]["t"],
                "network_weight": contribution[roi]["network_weight"],
                "numerator": contribution[roi]["numerator"],
                "denominator": contribution[roi]["denominator"],
            }
    return atlas