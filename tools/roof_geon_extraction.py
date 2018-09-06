#!/usr/bin/env python

"""
Wrapper tool to run Purdue and Columbia's roof geon extraction.

This script encapsulates running the Purdue and Columbia roof geon
extraction pipeline, including segmentation, curve fitting,
reconstruction, conversion from PLY to OBJ, and conversion from PLY to
geon JSON.
"""

import argparse
import itertools
import os
import shutil
import subprocess
import sys

from pathlib import Path

import roof_segmentation
import fitting_curved_plane
import geon_to_mesh
import ply2geon
import ply2obj


def convert_lastext_to_las(infile, outfile):
    subprocess.run(['txt2las', '-i', infile, '-o', outfile, '-parse', 'xyzc'],
                   check=True)


def main(args):
    # Configure argument parser
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--las',
        type=str,
        required=True,
        help='Point Cloud File in LAS format')
    parser.add_argument(
        '--cls',
        type=str,
        required=True,
        help='Class Label (CLS) file')
    parser.add_argument(
        '--dtm',
        type=str,
        required=True,
        help='Digital Terrain Model (DTM) file')
    parser.add_argument(
        '--output_dir',
        type=str,
        required=True,
        help='Output directory')
    parser.add_argument(
        '--model_prefix',
        type=str,
        required=True,
        help='Prefix for model files (e.g. "dayton_geon")')
    parser.add_argument(
        '--model_dir',
        type=str,
        required=True,
        help='Directory containing the model files')

    # Parse arguments
    args = parser.parse_args(args)

    # Create output directory
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    # Step #1
    # Run segmentation executable
    print("* Running Purdue's segmentation on P3D point cloud")
    subprocess.run(['segmentation', args.las, args.cls, args.dtm], check=True)
    # Output files:
    building_segmentation_txt = "{}_bd.txt".format(args.las)
    # Road segmentation output only produced when we have roads
    # labeled in the CLS file
    road_segmentation_txt = "{}_road_seg.txt".format(args.las)

    # Step #2
    # Run Columbia's roof segmentation script
    print("* Running Columbia's roof segmentation")
    roof_segmentation_png = os.path.join(args.output_dir, "roof_seg.png")
    roof_segmentation_txt = os.path.join(args.output_dir,
                                         "roof_seg_outlas.txt")
    roof_segmentation.main(['--model_prefix', args.model_prefix,
                            '--model_dir', args.model_dir,
                            '--input_pc', building_segmentation_txt,
                            '--output_png', roof_segmentation_png,
                            '--output_txt', roof_segmentation_txt])

    # Step #3
    # Run Columbia curve plane fitting
    print("* Running Columbia's curve fitting")
    curve_fitting_png = os.path.join(args.output_dir, "curve_fit.png")
    curve_fitting_geon = os.path.join(args.output_dir,
                                      "curve_fitting_output_geon.geon")
    curve_fitting_remaining_txt = \
        os.path.join(args.output_dir,
                     "curve_fitting_remaining_outlas.txt")
    fitting_curved_plane.main(['--input_pc', roof_segmentation_txt,
                               '--output_png', curve_fitting_png,
                               '--output_txt', curve_fitting_remaining_txt,
                               '--output_geon', curve_fitting_geon])

    # Step #4
    # Run Columbia curve mesh generation
    print("* Running Columbia's geon to mesh")
    mesh_output = os.path.join(args.output_dir, "output_curves.ply")
    geon_to_mesh.main(['--input_geon', curve_fitting_geon,
                       '--input_dtm', args.dtm,
                       '--output_mesh', mesh_output])

    # Step #3_5 (Note the step numbering here is in reference to the
    # data flow diagram provided by Purdue / Columbia)
    # Run Purdue's Segmentation / Reconstruction on the points
    # leftover from Columbia's roof segmentation
    # Purdue's Segmentation code expects a binary LAS file, so we
    # first convert it
    print("* Converting remaining points from las text to las")
    curve_fitting_remaining_las = \
        os.path.join(args.output_dir,
                     "curve_fitting_remaining_outlas.las")
    convert_lastext_to_las(curve_fitting_remaining_txt,
                           curve_fitting_remaining_las)

    print("* Running Purdue's segmentation on remaining points las")
    subprocess.run(['segmentation', curve_fitting_remaining_las], check=True)
    # Output:
    curve_fitting_remaining_las_seg = "{}_seg.txt".format(
        curve_fitting_remaining_las)

    # Step #3_6
    print("* Running Purdue's reconstruction on segmented remaining points")
    subprocess.run(['reconstruction',
                    curve_fitting_remaining_las_seg],
                   check=True)

    if os.path.exists(road_segmentation_txt):
        print("* Found road segmentation output")

        # Step #1_5
        # Process road segmentation results
        print("* Converting road segmentation points from las text to las")
        road_segmentation_las = "{}_road_seg.las".format(args.las)
        convert_lastext_to_las(road_segmentation_txt,
                               road_segmentation_las)

        print("* Running Purdue's segmentation on road points las")
        subprocess.run(['segmentation',
                        road_segmentation_las],
                       check=True)
        road_segmentation_las_seg = "{}_seg.txt".format(
            road_segmentation_las)

        # Step #1_6
        # Reconstruct road segmentation results
        print("* Running Purdue's reconstruction on segmented road points")
        subprocess.run(['reconstruction',
                        road_segmentation_las_seg], check=True)

    # Collate our ply files
    remaining_ply_dir = "{}_plys".format(curve_fitting_remaining_las_seg)
    road_ply_dir = "{}_plys".format(road_segmentation_las_seg)

    all_ply_dir = os.path.join(args.output_dir, "all_plys")

    # Move all ply files to the same directory
    for f in itertools.chain(Path(remaining_ply_dir).glob("*.ply"),
                             # Path.glob doesn't complain if the directory doesn't exist
                             Path(road_ply_dir).glob("*.ply"),
                             [mesh_output]):
        shutil.move(str(f), all_ply_dir)

    # Step #7
    # Convert all of our PLY files to OBJ
    ply2obj.main(['--ply_dir', all_ply_dir,
                  '--dem', args.dtm,
                  '--offset'])

    # Convert all PLY files to geon JSON
    ply2geon.main(['--ply_dir', all_ply_dir,
                   '--dem', args.dtm])


if __name__ == '__main__':
    main(sys.argv[1:])
