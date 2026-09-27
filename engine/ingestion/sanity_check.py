import os
import glob
import matplotlib.pyplot as plt
import rasterio
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import numpy as np

def get_latest_file(directory, extension):
    files = glob.glob(os.path.join(directory, f"*.{extension}"))
    if not files:
        return None
    return max(files, key=os.path.getctime)

def plot_geotiff(tiff_path, output_png, title, cmap, vmin=None, vmax=None):
    if not tiff_path or not os.path.exists(tiff_path):
        print(f"File not found: {tiff_path}")
        return

    with rasterio.open(tiff_path) as src:
        data = src.read(1)
        bounds = src.bounds

    fig = plt.figure(figsize=(10, 10))
    ax = plt.axes(projection=ccrs.PlateCarree())
    
    ax.set_extent([bounds.left, bounds.right, bounds.bottom, bounds.top], crs=ccrs.PlateCarree())

    # Add features
    ax.add_feature(cfeature.COASTLINE, linewidth=1.5, edgecolor='black')
    ax.add_feature(cfeature.BORDERS, linewidth=1, linestyle=':', edgecolor='black')
    
    # Plot data
    extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
    
    # Handle masked/no-data values
    data = np.where(data == 0, np.nan, data) if 'dwr' in title.lower() else data

    im = ax.imshow(data, extent=extent, transform=ccrs.PlateCarree(), cmap=cmap, origin='upper', vmin=vmin, vmax=vmax)
    
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    plt.title(title)
    
    plt.savefig(output_png, bbox_inches='tight', dpi=150)
    plt.close()
    print(f"Saved {output_png}")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    insat_dir = os.path.join(base_dir, '..', 'data', 'insat')
    dwr_dir = os.path.join(base_dir, '..', 'data', 'dwr_proxy')
    out_dir = os.path.join(base_dir, '..', 'data', 'sanity_check')
    
    latest_insat = get_latest_file(insat_dir, 'tif')
    latest_dwr = get_latest_file(dwr_dir, 'tif')
    
    if latest_insat:
        plot_geotiff(
            latest_insat, 
            os.path.join(out_dir, 'insat_sanity.png'), 
            "INSAT-3D Proxy (Thermal IR)", 
            cmap='viridis',
            vmin=200, vmax=300
        )
        
    if latest_dwr:
        plot_geotiff(
            latest_dwr, 
            os.path.join(out_dir, 'dwr_sanity.png'), 
            "DWR Proxy (Reflectivity dBZ)", 
            cmap='jet',
            vmin=0, vmax=60
        )
