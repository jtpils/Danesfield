
import argparse
import gdal
import gdalnumeric
import numpy
import scipy.ndimage as ndimage
import sys

def downsample(dtm):
    """
    Simple 2X downsampling, take every other pixel
    """
    return dtm[::2, ::2]


def upsample(dtm, out):
    """
    Simple 2X upsampling, duplicate pixels
    """
    # Adjust teh slicing for odd row count
    if out.shape[0] % 2 == 1:
        s0 = numpy.s_[:-1]
    else:
        s0 = numpy.s_[:]
    # Adjust the slicing for odd column count
    if out.shape[1] % 2 == 1:
        s1 = numpy.s_[:-1]
    else:
        s1 = numpy.s_[:]

    # copy in duplicate values for blocks of 2x2 pixels
    out[::2, ::2] = dtm
    out[1::2, ::2] = dtm[s0,:]
    out[::2, 1::2] = dtm[:,s1]
    out[1::2, 1::2] = dtm[s0,s1]


def recursive_fit_dtm(dtm, dsm, step=1, level=0):
    """
    Recursive function to apply multi-scale DTM fitting
    """
    # if the image is still larger than 100 pixels, downsample
    if numpy.min(dtm.shape) > 100:
        # downsample both the DTM and DSM
        sm_dtm = downsample(dtm)
        sm_dsm = downsample(dsm)
        # Recursively apply DTM fitting to the downsampled image
        sm_dtm, max_level = recursive_fit_dtm(sm_dtm, sm_dsm, step, level+1)
        # Upsample the DTM back to the original resolution
        upsample(sm_dtm, dtm)
        print("level {} of {}".format(level,max_level))
        # Decrease the step size exponentially when moving back down the pyramid
        step = step / (2 * 2 ** (max_level - level))
        # Decrease the number of iterations as well
        num_iter = max(1, int(100 / (2 ** (max_level - level))))
        # Apply iterations of cloth draping simulation to smooth out the result
        return drape_cloth(dtm, dsm, step, num_iter), max_level

    print("reached min size {}".format(dtm.shape))
    # Apply cloth draping at the coarsest level (base case)
    return drape_cloth(dtm, dsm, step, 100), level 


def drape_cloth(dtm, dsm, step=1, num_iter=10):
    """
    Compute inverted 2.5D cloth draping simulation iterations
    """
    print("draping:", end='')
    for i in range(num_iter):
        print(".", end='', flush=True)
        # raise the DTM by step (inverted gravity)
        dtm += step
        for i in range(10):
            # handle DSM intersections, snap back to below DSM
            numpy.minimum(dtm, dsm, out=dtm)
            # apply spring tension forces (blur the DTM)
            dtm = ndimage.uniform_filter(dtm, size=3)
    # print newline after progress bar
    print("")
    # one final intersection check
    numpy.minimum(dtm, dsm, out=dtm)
    return dtm


def fit_dtm(dsm, nodata_val):
    """
    Fit a Digital Terrain Model (DTM) to the provided Digital Surface Model (DSM)
    """
    # initialize DTM to a deep copy of the DSM
    dtm = dsm.copy()
    # get the range of valid height values (skipping no-data values)
    valid_data = dsm[dsm != nodata_val]
    minv = numpy.min(valid_data)
    maxv = numpy.max(valid_data)
    # replace no-data values in the DSM with the max height,
    # so all pixels now have a valid value
    dsm[dsm == nodata_val] = maxv
    # compute the step size that covers the range in 100 steps
    step = (maxv - minv) / 100
    # initialize the DTM values to the minimum DSM height
    dtm = numpy.full(dsm.shape, minv, dsm.dtype)
    return recursive_fit_dtm(dtm, dsm, step)[0]


def main(args):
    # Configure argument parser
    parser = argparse.ArgumentParser(
        description='Fit a DTM to a DSM')
    parser.add_argument("source_dsm",
                        help="Digital surface model (DSM) image file name")
    parser.add_argument("destination_dtm",
                        help="Digital terrain model (DTM) image file name")
    parser.add_argument('-t', "--thresh", type=float, default=1.0,
                        help="Threshold")
    args = parser.parse_args()

    # open the DSM
    dsm = gdal.Open(args.source_dsm, gdal.GA_ReadOnly)
    if not dsm:
        print("Unable to open {}".format(args.source_dsm))
        exit(1)
    band = dsm.GetRasterBand(1)
    dsmRaster = band.ReadAsArray(
        xoff=0, yoff=0,
        win_xsize=dsm.RasterXSize, win_ysize=dsm.RasterYSize)
    dsm_nodata_value = band.GetNoDataValue()
    print("DSM raster shape {}".format(dsmRaster.shape))

    dtm = dsmRaster


    # create the DTM image
    driver = dsm.GetDriver()
    driverMetadata = driver.GetMetadata()
    destImage = None
    if driverMetadata.get(gdal.DCAP_CREATE) == "YES":
        print("Create destination DTM of "
              "size:({}, {}) ...".format(dsm.RasterXSize, dsm.RasterYSize))
        options = []
        # ensure that space will be reserved for geographic corner coordinates
        # (in DMS) to be set later
        if (driver.ShortName == "NITF" and not projection):
            options.append("ICORDS=G")
        # If I try to use AddBand with GTiff I get:
        # Dataset does not support the AddBand() method.
        # So I create all bands using the same type at the begining
        destImage = driver.Create(
            args.destination_dtm, xsize=dtm.shape[1],
            ysize=dtm.shape[0],
            bands=dsm.RasterCount, eType=band.DataType,
            options=options)

        gdalnumeric.CopyDatasetInfo(dsm, destImage)
    else:
        print("Driver {} does not supports Create().".format(driver))
        sys.exit(1)

    dtm = fit_dtm(dtm, band.GetNoDataValue())
    #dtm[dtm < 2.0] = band.GetNoDataValue()

    destBand = destImage.GetRasterBand(1)
    destBand.SetNoDataValue(band.GetNoDataValue())
    destBand.WriteArray(dtm)


if __name__ == '__main__':
    main(sys.argv[1:])
