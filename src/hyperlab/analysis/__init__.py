"""Local descriptive analysis; outputs are differences, never defect diagnoses."""

from .core import (composite, difference, export_roi_csv, pca, ratio, reflectance,
                   roi_statistics, roi_comparison, spectral_angle)
from .capabilities import capabilities, feature_selection, require_capability
from .quality import cfa_statistics, quality_summary, TemporalStatistics
from .products import export_product

__all__ = ["composite", "difference", "ratio", "roi_statistics", "roi_comparison", "export_roi_csv",
           "pca", "spectral_angle", "reflectance", "capabilities", "feature_selection",
           "require_capability", "cfa_statistics", "quality_summary", "TemporalStatistics", "export_product"]
