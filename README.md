
![c](https://03c8.net/images/euler_bricks_banner.png)

----------

#### Info:

 Problem: http://en.wikipedia.org/wiki/Euler_brick

 A "brick" is a cuboid where the length of all the edges are integers and all of the diagonals of the faces are integers as well. All sides must also be different.

 ![c](https://03c8.net/images/euler_bricks_example.gif)
 
 Euler-Bricks tries to calculate (brute-force) as many different "bricks" where the sides are less than X.

 To calculate a "brick" means to find the lengths of the edges and the lengths of the diagonals of the faces of a valid Euler's "brick".

 You can visualize plotting graphs with results, store math 'bricks' relationships (so the tool doesn't need to process again similar data) 
 and organized auto-save your results, for example, to be used on a future for BigData processing or AI maths solving tasks.

#### Installing:

 This tool runs on many platforms and it requires Python (3.x.y). To generate graphs, you need to install the following library:

       python3-matplotlib - Python based plotting system in a style similar to Matlab (Python 3)

 On Debian-based systems (ex: Ubuntu), run: 

       sudo apt-get install python3-matplotlib

 Or:

       pip3 install matplotlib

#### Executing:
  
  python3 euler-bricks

 Interactive mode (prompts for mode/range, pops up a 3D plot per brick) works
 exactly as before. For unattended/headless runs, pass flags instead:

       python3 euler-bricks --range 1-100000 --no-gui --log results.csv

 * `--range MIN-MAX` — skip the prompts and search this range directly.
 * `--no-gui` — never import matplotlib; just print and/or log results
   (matplotlib doesn't even need to be installed in this mode).
 * `--mode {manual,learning}` — manual pops up each plot; learning saves the
   PNG but skips the popup.
 * `--log FILE` — append every found brick to FILE as CSV
   (`a,b,c,dZY,dXZ,dXY,space_diagonal,perfect_cuboid`), so long unattended
   runs don't rely on scraping stdout or the saved PNGs.

 As of this extension the searcher also checks the **space diagonal**
 (`sqrt(a²+b²+c²)`) of every Euler brick it finds. If that's an integer too,
 it's a genuine **perfect cuboid** — the open problem this tool's banner
 asks about — and it's flagged distinctly on stdout, in the CSV log, and in
 the saved plot (gold faces, `PERFECT_CUBOID-` filename prefix) instead of
 silently being reported as an ordinary Euler brick. The integer checks
 themselves now use `math.isqrt` instead of `math.sqrt(...).is_integer()`,
 which avoids float-precision false positives/negatives once edge lengths
 get large.

----------

####  Source libs:

 * PyMatplotlib: https://pypi.python.org/pypi/matplotlib

#### License:

 Euler-Bricks is released under the GPLv3.

#### Contact:

      - psy (epsylon@riseup.net)

#### Contribute: 

 To make donations use the following hash:
  
     - Bitcoin: 19aXfJtoYJUoXEZtjNwsah2JKN9CK5Pcjw

----------

####  Screenshots:

  ![c](https://03c8.net/images/euler_bricks_example.png)

  ![c](https://03c8.net/images/euler_bricks_example2.png)

