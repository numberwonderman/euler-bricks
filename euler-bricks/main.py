#!/usr/bin/env python3
# -*- coding: utf-8 -*-"
"""
Euler-Bricks - 2020 - by psy (epsylon@riseup.net)

Extended: exact integer perfect-square checks (no float precision loss),
perfect-cuboid (space-diagonal) detection, CSV result logging, and a
non-interactive --range/--no-gui CLI mode for unattended/headless runs.

You should have received a copy of the GNU General Public License along
with Euler-Bricks; if not, write to the Free Software Foundation, Inc., 51
Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
"""
import argparse
import csv
import math
import os
import sys

LEARNING_MODES = {"l", "learn", "learning"}


class EulerBrick(object):
    def __init__(self):
        self.store_bricks = "bricks/"
        self.mode = "manual"
        self.no_gui = False
        self.log_file = None

    def banner(self):
        print(75*"=")
        print("  _____      _           ____       _      _         ")
        print(" | ____|   _| | ___ _ __| __ ) _ __(_) ___| | _____  ")
        print(" |  _|| | | | |/ _ \\ '__|  _ \\| '__| |/ __| |/ / __| ")
        print(" | |__| |_| | |  __/ |  | |_) | |  | | (__|   <\\__ \\ ")
        print(" |_____\\__,_|_|\\___|_|  |____/|_|  |_|\\___|_|\\_\\___/ ")
        print("                                                     ")
        print(75*"=","\n")
        print(" Does a 'perfect cuboid' exist?\n")
        print(75*"=","\n")

    def run(self, args=None):
        self.banner()
        if args is not None and args.range_:
            self.mode = args.mode
            self.root = args.range_
            self.no_gui = args.no_gui
            self.log_file = args.log_file
        else:
            self.mode = input(" -Set mode: manual (default), learning (M/l): ")
            self.root = input(" -Set range (ex: 1-1000 or 1000-1000000 (PRESS ENTER = 1-1000) (STOP = CTRL+z): ")
            if not self.root:
                self.root = "1-1000"
            self.no_gui = False
            self.log_file = None
        print("\n[Info] Looking for 'bricks' in the range: "+ str(self.root)+ "\n")
        self.generate_bricks(self.root)

    @staticmethod
    def is_perfect_square(n):
        """Exact integer perfect-square test (math.isqrt has no float
        precision loss, unlike math.sqrt(n).is_integer() on large n)."""
        if n < 0:
            return False, 0
        r = math.isqrt(n)
        return (r * r == n), r

    def log_result(self, a, b, c, d, e, f, g, perfect):
        if not self.log_file:
            return
        is_new = not os.path.exists(self.log_file)
        with open(self.log_file, "a", newline="") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(["a", "b", "c", "dZY", "dXZ", "dXY", "space_diagonal", "perfect_cuboid"])
            writer.writerow([a, b, c, d, e, f, g if g is not None else "", perfect])

    def generate_bricks(self, rng):
        srng = rng.split('-')
        try:
            minrange = int(srng[0])
            maxrange = int(srng[1])
        except (ValueError, IndexError):
            print(40*"-"+"\n")
            print("[Error] Numbers on range should be integers (ex: 1-1000). Aborting...\n")
            sys.exit(2)
        if minrange >= maxrange:
            print(40*"-"+"\n")
            print("[Error] Min range should be minor than max range (ex: 1-1000). Aborting...\n")
            sys.exit(2)
        self.init = minrange
        self.end = maxrange
        n = 1
        if not self.no_gui and not os.path.exists(self.store_bricks):
            os.mkdir(self.store_bricks)
        for a in range(self.init, self.end):
            asq = a * a
            for b in range(a, self.end):
                bsq = b * b
                d_ok, d = self.is_perfect_square(asq + bsq)
                if not d_ok:
                    continue
                for c in range(b, self.end):
                    n = n + 1
                    csq = c * c
                    e_ok, e = self.is_perfect_square(asq + csq)
                    if not e_ok:
                        continue
                    f_ok, f = self.is_perfect_square(bsq + csq)
                    if not f_ok:
                        continue
                    g_ok, g = self.is_perfect_square(asq + bsq + csq)
                    print(40*"-"+"\n")
                    if g_ok:
                        print("[!!!] PERFECT CUBOID FOUND -- space diagonal is also an integer!\n")
                    else:
                        print("[Info] Found 'brick'!!\n")
                    print(" -ID: {} ({})".format(n, str(c)+':'+str(b)+':'+str(a)))
                    print(" -Hedges: X={} Y={} Z={}".format(c, b, a))
                    print(" -Diagonals: dZY={} dXZ={} dXY={}".format(d, e, f))
                    if g_ok:
                        print(" -Space diagonal: g={}".format(g))
                    self.log_result(a, b, c, d, e, f, g if g_ok else None, g_ok)
                    if not self.no_gui:
                        self.draw(a, b, c, d, e, f, n, perfect=g_ok)

    def draw(self, a, b, c, d, e, f, n, perfect=False):
        import numpy as np
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        import matplotlib.pyplot as plt
        plt.rcParams.update({'figure.max_open_warning': 0})

        points = np.array([[c, b, a],
                  [c, -b, -a],
                  [c, b, -a ],
                  [-c, b, -a],
                  [-c, -b, a],
                  [c, -b, a ],
                  [c, b, a  ],
                  [-c, b, a]])
        P = [[2.06498904e-01 , -6.30755443e-07 ,  1.07477548e-03],
            [1.61535574e-06 ,  1.18897198e-01 ,  7.85307721e-06],
            [7.08353661e-02 ,  4.48415767e-06 ,  2.05395893e-01]]
        Z = np.zeros((8,3))
        for i in range(8): Z[i,:] = np.dot(points[i,:],P)
        Z = 1*Z
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
        r = [-1,1]
        X, Y = np.meshgrid(r, r)
        ax.scatter3D(Z[:, 0], Z[:, 1], Z[:, 2])
        verts = [[Z[0],Z[1],Z[2],Z[3]],
                [Z[4],Z[5],Z[6],Z[7]],
                [Z[0],Z[1],Z[5],Z[4]],
                [Z[2],Z[3],Z[7],Z[6]],
                [Z[1],Z[2],Z[6],Z[5]],
                [Z[4],Z[7],Z[3],Z[0]]]
        verts2 = [[-Z[0],-Z[1],-Z[2],-Z[3]],
                [-Z[4],-Z[5],-Z[6],-Z[7]],
                [-Z[0],-Z[1],-Z[5],-Z[4]],
                [-Z[2],-Z[3],-Z[7],-Z[6]],
                [-Z[1],-Z[2],-Z[6],-Z[5]],
                [-Z[4],-Z[7],-Z[3],-Z[0]]]
        facecolor = 'gold' if perfect else 'cyan'
        ax.add_collection3d(Poly3DCollection(verts, facecolors=facecolor, linewidths=1, edgecolors='r', alpha=.25))
        ax.add_collection3d(Poly3DCollection(verts2, facecolors=facecolor, linewidths=0, edgecolors='r', alpha=.25))
        ax.set_xlabel("X: {} dXY: {} dXZ: {}".format(int(c),int(f),int(e)))
        ax.set_ylabel("Y: {} dYX: {} dYZ: {}".format(int(b),int(f),int(d)))
        ax.set_zlabel("Z: {} dZX: {} dZY: {}".format(int(a),int(e),int(d)))
        ax.w_xaxis.set_ticklabels("")
        ax.w_yaxis.set_ticklabels("")
        ax.w_zaxis.set_ticklabels("")
        title = "PERFECT CUBOID" if perfect else "Euler's brick"
        header = "[{} {}".format(title, "x:"+str(c)+' y:'+str(b)+' z:'+str(a) + "]\n")
        fig.canvas.set_window_title("Euler's brick ID: {} ".format(n))
        plt.title(header)
        prefix = "PERFECT_CUBOID-" if perfect else ""
        outfile = self.store_bricks+prefix+str(c)+'_'+str(b)+'_'+str(a)+"-euler_brick.png"
        if not os.path.exists(outfile):
            fig.savefig(outfile)
            print("\n[Info] Generated 'brick' image at: "+outfile+"\n")
        else:
            print("\n[Info] You have previously saved this 'brick'...\n")
        if self.mode.strip().lower() not in LEARNING_MODES:
            plt.show()
        ax.clear()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Euler brick / perfect cuboid brute-force searcher")
    parser.add_argument("--range", dest="range_", metavar="MIN-MAX",
        help="Search range, e.g. 1-1000. Skips the interactive prompts.")
    parser.add_argument("--mode", choices=["manual", "learning"], default="manual",
        help="manual: pop up each 3D plot (default). learning: skip plot popups.")
    parser.add_argument("--no-gui", action="store_true",
        help="Headless mode: never import matplotlib, just print/log results.")
    parser.add_argument("--log", dest="log_file", metavar="FILE",
        help="Append every found brick (and any perfect cuboid) to FILE as CSV.")
    return parser.parse_args()


if __name__ == "__main__":
    app = EulerBrick()
    app.run(parse_args())
