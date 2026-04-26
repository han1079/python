import numpy as np
import pdb
from matplotlib import pyplot as plt
from matplotlib.animation import FuncAnimation
from scipy.sparse import diags
from scipy.sparse.linalg import splu

# Physical Properties
hbar = 1; # Using normalized planck
m = 1; # Using normalized mass

# ---------------------------
# Grid (normalized coordinate)
# ---------------------------
N = 2000
x0, x1 = 0.0, 1.0
x = np.linspace(x0, x1, N)
dx = x[1] - x[0]

# ---------------------------
# Finite square well potential
# V(x) = -V0 inside [a,b], 0 outside
# ---------------------------
V0 = 10000.0          # well depth (positive number; potential will be negative inside)
a, b = 0.20, 0.80  # well region in normalized coordinates

V = np.ones(N, dtype=float)*V0
V[(x >= a) & (x <= b)] = 0

# ---------------------------
# Dirichlet endpoint values (fixed)
# ---------------------------
psi_left  = 0.0 + 0.0j
psi_right = 0.0 + 0.0j

# ---------------------------
# Example wavefunction container (complex math ready)
# ---------------------------
psi = np.zeros(N, dtype=np.complex128)
psi[0]  = psi_left
psi[-1] = psi_right

# Optional: seed interior with something nontrivial (so evolution does anything)
# e.g., a Gaussian packet (still Dirichlet at endpoints)
x_c, sigma, k0 = 0.40, 0.005, -50.0
psi[1:-1] = np.exp(-0.5*((x[1:-1]-x_c)/sigma)**2) * np.exp(1j*k0*x[1:-1])

# Optional: normalize (discrete L2 with dx)
norm = np.sqrt(np.sum(np.abs(psi)**2) * dx)
psi /= norm

psi[0] = psi_left
psi[-1] = psi_right
# Build the static hamiltonian matrix
t = hbar**2 / (2*m*dx**2)

class PsiPlot:
  def __init__(self, sys):
    self.sys = sys
    _psi_V, psi_ax = plt.subplots()
    psi_V_ax = psi_ax.twinx()
    psi_ax.set_ylim((-1,1))
    psi_V_ax.set_ylim((V.min()*1.05, np.maximum(V.max()*1.05, V.max()+0.5)))
    psi_re, = psi_ax.plot(x, np.zeros(np.size(x)), color="blue")
    psi_im, = psi_ax.plot(x, np.zeros(np.size(x)), color="red")
    psi_V, = psi_V_ax.plot(x, np.zeros(np.size(x)), color="black")

    _p_V, p_ax = plt.subplots()
    V_ax = p_ax.twinx()
    p_ax.set_ylim((0, 1))
    V_ax.set_ylim((V.min()*1.05, np.maximum(V.max()*1.05, V.max()+0.5)))
    p_V, = V_ax.plot(x, np.zeros(np.size(x)), color="black")
    p_p, = p_ax.plot(x, np.zeros(np.size(x)), color="red")


    self.psi = sys.psi0

    class Fig:
      def __init__(self, fig, lines, updater=None):
        self.fig = fig
        self.lines = lines
        self.updater = updater

    self.psi_V_fig = Fig(_psi_V,
                         {"psi_re": psi_re,
                          "psi_im": psi_im,
                          "V": psi_V},
                         self.psi_V_updater)


    self.p_V_fig = Fig(_p_V,
                       {"psi2": p_p,
                        "V": p_V,},
                       self.p_V_updater)

    self.figures = [self.psi_V_fig, self.p_V_fig]

    self.last_frame = -1

  def update_state(self, reset=False):
    if reset is False:
      self.psi[1:-1] = self.sys._psi_time_step(self.psi, reset=False)
    else:
      self.psi[1:-1] = self.sys._psi_time_step(self.psi, reset=True)

  def _check_frame_and_update(self, frame):
    # Gets run in multiple updaters. Frame check allows bypassing
    # of double calculations

    if frame == self.last_frame:
      return

    if frame > self.last_frame:
      steps = frame - self.last_frame
      for _ in range(steps):
          self.update_state()
      self.last_frame = frame


    if frame < self.last_frame:
      self.update_state(reset=True)
      self.last_frame = frame




  def psi_V_updater(self, frame):
    self._check_frame_and_update(frame)
    _re = np.real(self.psi)
    _im = np.imag(self.psi)
    self.psi_V_fig.lines["psi_re"].set_ydata(_re)
    self.psi_V_fig.lines["psi_im"].set_ydata(_im)
    self.psi_V_fig.lines["V"].set_ydata(self.sys.V)
    return tuple(self.psi_V_fig.lines.values())

  def p_V_updater(self, frame):
    print(f"\r{np.sum(self.psi*np.conj(self.psi))}", end="", flush=True)
    self._check_frame_and_update(frame)
    self.p_V_fig.lines["psi2"].set_ydata(self.psi*np.conj(self.psi))
    self.p_V_fig.lines["V"].set_ydata(self.sys.V)
    return tuple(self.p_V_fig.lines.values())



class EigenSystem:
  def __init__(self, V):
    self.dt = 0.00005
    self.H, self.A, self.A_lu, self.B = self._update_hamiltonian(V)
    print(np.max(np.abs(self.H - self.H.conj().T)))
    self.V = V

    self.eigenvalues, self.eigenvectors_T = np.linalg.eigh(self.H.toarray())
    self.eigenvectors = self.eigenvectors_T.T
    print(np.shape(self.eigenvectors))
    self.stationary_states = np.zeros((N-2,N), dtype=np.complex128)
    self.energy_bands = np.zeros((N-2,N))



    for i in range(N-2):
      self.stationary_states[i][1:-1] = self.eigenvectors[i]
      self.energy_bands[i] = np.ones(N)*self.eigenvalues[i]

    #self.psi0 = self.stationary_states[30] 
    self.psi0 = psi
    self.frame = 0

  def _update_hamiltonian(self, V):
    M = N-2
    t= hbar**2 / (2*m*dx**2)
    dt_a = self.dt / (2*hbar)

    H_diag = 2*t + V[1:-1]
    H_off_diag = -t*np.ones(M-1)

    A = diags(
        [1j*dt_a*H_off_diag, 1 + (1j*dt_a*H_diag), 1j*dt_a*H_off_diag],
        offsets=[-1, 0, 1],
        format="csc"
    )

    A_lu = splu(A)

    B = diags(
        [-1j*dt_a*H_off_diag, 1 - (1j*dt_a*H_diag), -1j*dt_a*H_off_diag],
        offsets=[-1, 0, 1],
        format="csc"
    )

    H = diags(
        [H_off_diag, H_diag, H_off_diag],
        offsets=[-1, 0, 1],
        format="csc"
    )

    assert np.allclose(H.toarray(), H.toarray().conj().T)

    return H, A, A_lu, B

  def _solve_psi_at_t(self, E, psi, t):
    psi_t = np.exp(-1j * E * t / hbar) * psi
    return psi_t

  def _psi_time_step(self, psi=None, reset=False):
    if psi is None:
      psi = self.psi0

    if reset is True:
      return self.psi0[1:-1]

    if np.sqrt(np.sum(psi*np.conj(psi))*dx) > 1.01 or np.sqrt(np.sum(psi*np.conj(psi))*dx) < 0.99: 
      print("State norm:", np.sqrt(np.sum(np.abs(psi)**2)*dx)) 

    rhs = self.B @ psi[1:-1]
    psi_t = self.A_lu.solve(rhs)
    return psi_t



psi = EigenSystem(V)
psiplot = PsiPlot(psi)

frames = 1000

class Animator:
    def __init__(self, sys):
        self.sys = sys
        # self.animation_plots = []

        # for figure in self.sys.figures:
        #     anim = FuncAnimation(figure.fig, figure.updater, frames=frames, interval=100, blit=True, repeat=True)
        #     self.animation_plots.append(anim)
        self.animation_plot = FuncAnimation(sys.psi_V_fig.fig, sys.psi_V_fig.updater, frames=frames, interval=10, blit=False)
        self.animation_plot2 = FuncAnimation(sys.p_V_fig.fig, sys.p_V_fig.updater, frames=frames, interval=10, blit=False)

    def run(self):
        plt.show()

a = Animator(psiplot)

a.run()
