"""Tk desktop controls with explicit source labels and queued background work."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from hyperlab.analysis import composite, difference, export_roi_csv, pca, ratio, roi_statistics, spectral_angle
from hyperlab.io import load_cube, make_synthetic_cube
from hyperlab.probe import candidates, load_snapshot, run_inventory


class HyperLabApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("HyperLab — instrument recovery and local analysis")
        self.root.geometry("1220x900")
        self.cube = None
        self.snapshot = None
        self.roi_results = None
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.close_requested = False
        self.source = tk.StringVar(value="LIVE — no acquisition session; connection not yet checked")
        self.device_status = tk.StringVar(value="Not refreshed. Run the read-only inventory to check the current device and driver. Scan API and calibration remain unverified.")
        self.status = tk.StringVar(value="Ready. Offline tools do not validate the instrument.")
        self.output = tk.StringVar(value=str(Path("local/exports").resolve()))
        self.axis_order = tk.StringVar(value="")
        self.dataset = tk.StringVar(value="")
        self.cti = tk.StringVar(value="")
        self.serial = tk.StringVar(value="")
        self.capture_format = tk.StringVar(value="current")
        self.exposure_us = tk.StringVar(value="")
        self.gain_db = tk.StringVar(value="")
        self.capture_status = tk.StringVar(value="Single frame not ready. Spectroscopy BLOCKED: scan protocol and calibration unverified.")
        self._build()
        self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.cti.trace_add("write", lambda *_: self.update_capture_gate())
        self.serial.trace_add("write", lambda *_: self.update_capture_gate())
        self._fill_installed_producer()

    def _fill_installed_producer(self):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
                install = Path(winreg.QueryValueEx(key, "MVIMPACT_ACQUIRE_DIR")[0])
            producer = install / "bin" / "x64" / "mvGenTLProducer.cti"
            if producer.is_file():
                self.cti.set(str(producer))
        except (ImportError, OSError):
            pass

    def _build(self):
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, textvariable=self.source, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        hardware = ttk.LabelFrame(outer, text="Instrument", padding=6)
        hardware.pack(fill="x", pady=4)
        ttk.Label(hardware, textvariable=self.device_status, wraplength=1150).pack(anchor="w")
        actions = ttk.Frame(hardware)
        actions.pack(fill="x", pady=3)
        self.probe_button = ttk.Button(actions, text="Refresh read-only device inventory", command=self.probe)
        self.probe_button.pack(side="left")
        self.hardware_buttons = []
        for name in ("Connect", "Single frame", "Start scan", "Stop scan"):
            button = ttk.Button(actions, text=name, state="disabled")
            button.pack(side="left", padx=3)
            self.hardware_buttons.append(button)
        self.hardware_buttons[1].configure(command=self.capture)
        self.hardware_buttons[0].configure(command=self.probe, state="normal")
        runtime = ttk.Frame(hardware)
        runtime.pack(fill="x", pady=2)
        ttk.Label(runtime, text="Reviewed mvGenTLProducer.cti:").pack(side="left")
        ttk.Entry(runtime, textvariable=self.cti).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Label(runtime, text="Exact module serial:").pack(side="left")
        ttk.Entry(runtime, textvariable=self.serial, width=22).pack(side="left", padx=4)
        settings = ttk.Frame(hardware)
        settings.pack(fill="x", pady=2)
        ttk.Label(settings, text="Frame format:").pack(side="left")
        self.format_control = ttk.Combobox(settings, textvariable=self.capture_format, values=("current", "RGB8", "BayerRG12"), width=12, state="disabled")
        self.format_control.pack(side="left", padx=4)
        ttk.Label(settings, text="Exposure µs:").pack(side="left")
        exposure_control = ttk.Entry(settings, textvariable=self.exposure_us, width=12, state="disabled")
        exposure_control.pack(side="left", padx=4)
        ttk.Label(settings, text="Gain dB:").pack(side="left")
        gain_control = ttk.Entry(settings, textvariable=self.gain_db, width=8, state="disabled")
        gain_control.pack(side="left", padx=4)
        self.session_controls = [exposure_control, gain_control]
        ttk.Label(settings, text="Blank = keep current. Session changes are checked and restored after capture.").pack(side="left", padx=6)
        ttk.Label(hardware, textvariable=self.capture_status).pack(anchor="w")

        files = ttk.Frame(outer)
        files.pack(fill="x", pady=4)
        ttk.Button(files, text="Open local data", command=self.open_file).pack(side="left")
        ttk.Button(files, text="Synthetic example", command=self.synthetic).pack(side="left", padx=4)
        ttk.Label(files, text="Unmapped array axes:").pack(side="left", padx=(10, 2))
        ttk.Combobox(files, textvariable=self.axis_order, values=("", "HW", "HWK", "HKW", "KHW", "KWH", "WHK", "WKH"), width=6, state="readonly").pack(side="left")
        ttk.Label(files, text="NPZ dataset:").pack(side="left", padx=(10, 2))
        ttk.Entry(files, textvariable=self.dataset, width=16).pack(side="left")
        out = ttk.Frame(outer)
        out.pack(fill="x")
        ttk.Label(out, text="Output directory:").pack(side="left")
        ttk.Entry(out, textvariable=self.output).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(out, text="Browse", command=self.choose_output).pack(side="left")

        band = ttk.Frame(outer)
        band.pack(fill="x", pady=4)
        self.axis_caption = ttk.Label(band, text="Band / state:")
        self.axis_caption.pack(side="left")
        self.band = tk.IntVar(value=0)
        self.slider = tk.Scale(band, from_=0, to=0, orient="horizontal", variable=self.band, command=lambda _: self.show_band(), showvalue=True, resolution=1)
        self.slider.pack(side="left", fill="x", expand=True)
        self.band_label = ttk.Label(band, text="No array loaded")
        self.band_label.pack(side="left", padx=6)
        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=3)
        self.channels = [tk.IntVar(value=value) for value in (0, 1, 2)]
        self.channel_controls = []
        ttk.Label(controls, text="Composite indices:").pack(side="left")
        for variable in self.channels:
            control = ttk.Spinbox(controls, from_=0, to=100000, textvariable=variable, width=5)
            control.pack(side="left", padx=2)
            self.channel_controls.append(control)
        self.composite_button = ttk.Button(controls, text="Composite", command=self.show_composite)
        self.composite_button.pack(side="left", padx=3)
        self.analysis_buttons = []
        for label, command in (("PCA", self.show_pca), ("Angle to ROI 1", self.show_angle)):
            button = ttk.Button(controls, text=label, command=command)
            button.pack(side="left", padx=3)
            self.analysis_buttons.append(button)
        self.pair = [tk.IntVar(value=value) for value in (0, 1)]
        ttk.Label(controls, text="Difference / ratio A,B:").pack(side="left", padx=(8, 2))
        for variable in self.pair:
            ttk.Spinbox(controls, from_=0, to=100000, textvariable=variable, width=5).pack(side="left", padx=2)
        for label, command in (("A - B", lambda: self.show_pair("difference")), ("A / B", lambda: self.show_pair("ratio"))):
            button = ttk.Button(controls, text=label, command=command)
            button.pack(side="left", padx=3)
            self.analysis_buttons.append(button)

        rois = ttk.Frame(outer)
        rois.pack(fill="x", pady=3)
        self.roi_vars = []
        for number in (1, 2):
            ttk.Label(rois, text=f"ROI {number} x0,y0,x1,y1:").pack(side="left", padx=(4, 2))
            variables = [tk.IntVar(value=value) for value in (0, 0, 1, 1)]
            self.roi_vars.append(variables)
            for variable in variables:
                ttk.Entry(rois, textvariable=variable, width=5).pack(side="left", padx=1)
        for label, command in (("ROI curves", self.show_rois), ("Export ROI CSV", self.export_rois)):
            button = ttk.Button(rois, text=label, command=command)
            button.pack(side="left", padx=3)
            self.analysis_buttons.append(button)

        self.figure = Figure(figsize=(11, 4.3), dpi=100, constrained_layout=True)
        self.image_axis, self.curve_axis = self.figure.subplots(1, 2)
        self.image_axis.set_title("Image / difference score")
        self.curve_axis.set_title("ROI curves")
        self.canvas = FigureCanvasTkAgg(self.figure, master=outer)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        progress = ttk.Frame(outer)
        progress.pack(fill="x")
        self.progress = ttk.Progressbar(progress, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.stop_button = ttk.Button(progress, text="Stop background result", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=4)
        ttk.Label(outer, textvariable=self.status, wraplength=1160).pack(anchor="w", pady=2)
        self.log = tk.Text(outer, height=4, wrap="word", state="disabled")
        self.log.pack(fill="x")

    def write_log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", datetime.now().strftime("%H:%M:%S ") + str(message) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        self.status.set(str(message))

    def worker(self, label, function, callback):
        if self.busy:
            self.write_log("A background operation is already running.")
            return
        self.busy = True
        self.cancel.clear()
        self.progress.start(12)
        self.stop_button.configure(state="normal")
        self.probe_button.configure(state="disabled")
        self.hardware_buttons[0].configure(state="disabled")
        self.update_capture_gate()
        self.write_log(label)

        def run():
            try:
                self.events.put((callback, function(), None))
            except Exception as error:
                self.events.put((callback, None, error))

        threading.Thread(target=run, daemon=True).start()

    def _poll(self):
        try:
            callback, value, error = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            self.stop_button.configure(state="disabled")
            self.probe_button.configure(state="normal")
            self.hardware_buttons[0].configure(state="normal")
            self.update_capture_gate()
            if self.cancel.is_set():
                self.write_log("Background operation finished; its result was discarded after Stop. Files already saved remain on disk.")
            elif error:
                self.write_log(f"Operation failed: {error}")
                messagebox.showerror("HyperLab", str(error), parent=self.root)
            else:
                try:
                    callback(value)
                except Exception as callback_error:
                    self.write_log(f"Cannot display result: {callback_error}")
            if self.close_requested:
                self.root.destroy()
                return
        self.root.after(100, self._poll)

    def close(self):
        if self.busy:
            self.close_requested = True
            self.cancel.set()
            self.write_log("Closing after the current bounded operation returns and releases its resources.")
        else:
            self.root.destroy()

    def stop(self):
        self.cancel.set()
        self.write_log("Stop requested. The current bounded file/analysis operation finishes before its result is discarded; this is not a hardware stop.")

    def probe(self):
        def complete(path):
            self.set_snapshot(load_snapshot(path))
            self.write_log(f"Read-only inventory saved: {path}. No stream or serial port opened.")
        self.worker("Enumerating present devices without opening them…", run_inventory, complete)

    def set_snapshot(self, snapshot):
        self.snapshot = snapshot
        leads = candidates(snapshot)
        summary = "; ".join(f"{entry['device']['friendly_name']}: code {entry['device']['problem_code']} ({entry['role']})" for entry in leads)
        self.device_status.set(summary or "No instrument identity leads detected. IDENTITY_UNCONFIRMED.")
        imaging = [device for device in snapshot["devices"] if device.get("present", True) and device.get("vid") == "164C" and device.get("pid") == "5533" and device.get("interface") == "00"]
        if len(imaging) == 1:
            parents = [device for device in snapshot["devices"] if device["instance_id"] == imaging[0].get("parent") and device.get("vid") == "164C" and device.get("pid") == "5533"]
            if len(parents) == 1:
                self.serial.set(parents[0]["instance_id"].rsplit("\\", 1)[-1])
        self.update_capture_gate()

    def update_capture_gate(self):
        ready = False
        if self.snapshot and not self.busy and self.serial.get().strip():
            parents = [entry["device"] for entry in candidates(self.snapshot) if entry["device"].get("vid") == "164C" and entry["device"].get("interface") == "unknown" and entry["device"]["instance_id"].rsplit("\\", 1)[-1] == self.serial.get().strip()]
            parent_ids = {device["instance_id"] for device in parents}
            interfaces = [device for device in self.snapshot["devices"] if device.get("parent") in parent_ids and device.get("interface") == "00" and device.get("problem_code") == 0 and (device.get("driver") or {}).get("inf", "unknown") != "unknown"]
            producer = Path(self.cti.get())
            ready = bool(interfaces) and producer.is_file() and producer.name == "mvGenTLProducer.cti"
        self.hardware_buttons[1].configure(state="normal" if ready else "disabled")
        self.format_control.configure(state="readonly" if ready else "disabled")
        for control in self.session_controls:
            control.configure(state="normal" if ready else "disabled")
        self.capture_status.set(("Single frame ready: selected imaging interface driver code 0." if ready else "Single frame not ready: check inventory, producer and exact serial.") + " Spectroscopy BLOCKED: scan protocol and calibration unverified.")
        return ready

    def capture_options(self):
        selected = self.capture_format.get()
        if selected not in ("current", "RGB8", "BayerRG12"):
            raise ValueError("Select current, RGB8 or BayerRG12 frame format")
        values = {"pixel_format": None if selected == "current" else selected}
        for name, variable in (("exposure_us", self.exposure_us), ("gain", self.gain_db)):
            text = variable.get().strip()
            value = float(text) if text else None
            if value is not None and not np.isfinite(value):
                raise ValueError("Exposure and gain must be finite numbers or blank")
            values[name] = value
        return values

    def capture(self):
        if not self.update_capture_gate():
            self.write_log("Capture blocked: refresh inventory and provide the reviewed producer plus the exact healthy imaging-module serial.")
            return
        from hyperlab.adapters.gentl import capture_single
        try:
            options = self.capture_options()
        except ValueError as error:
            self.write_log(f"Invalid capture setting: {error}")
            messagebox.showerror("Capture settings", str(error), parent=self.root)
            return
        producer, serial = self.cti.get(), self.serial.get().strip()
        directory = Path(self.output.get()) / ("raw_frame_" + datetime.now().strftime("%Y%m%dT%H%M%S%f"))
        def complete(path):
            self.set_cube(load_cube(path), str(path))
            self.write_log(f"LIVE capture saved and reopened as REPLAY: {path}. Physical scene-change validation is still required; this is not a spectrum.")
        self.worker("LIVE: capturing one raw sensor frame through the reviewed producer…", lambda: capture_single(producer, serial, directory, **options), complete)

    def synthetic(self):
        if self.busy:
            self.write_log("Wait for or stop the current background result before changing data.")
            return
        self.set_cube(make_synthetic_cube(), "generated example")

    def choose_output(self):
        path = filedialog.askdirectory(parent=self.root, initialdir=self.output.get())
        if path:
            self.output.set(path)

    def open_file(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("Supported local arrays", "*.hdr *.npy *.npz"), ("All files", "*.*")])
        if path:
            self.load_path(path)

    def load_path(self, path):
        options = {"axis_order": self.axis_order.get() or None, "dataset": self.dataset.get() or None}
        self.worker(f"Opening {path}", lambda: load_cube(path, **options), lambda cube: self.set_cube(cube, str(path)))

    def set_cube(self, cube, origin):
        self.cube = cube
        self.roi_results = None
        synthetic = cube.metadata.get("synthetic") is True or str(cube.metadata.get("data_source", "")).upper() == "SYNTHETIC"
        self.source.set(("SYNTHETIC" if synthetic else "REPLAY") + " — " + str(cube.metadata.get("data_level", "array")))
        color = self.color_channels()
        if color:
            self.source.set(self.source.get() + " — " + "/".join(color) + " color channels; not spectral bands")
        self.axis_caption.configure(text="Color channel:" if color else ("Sensor plane:" if cube.metadata.get("data_level") == "raw_frame" else "Band / state:"))
        self.composite_button.configure(text="Color preview" if color else "Composite")
        for control in self.analysis_buttons + self.channel_controls:
            control.configure(state="disabled" if color else "normal")
        height, width, count = cube.shape
        self.slider.configure(to=count - 1)
        self.band.set(0)
        for variable, value in zip(self.channels, (0, count // 2, count - 1)):
            variable.set(value)
        self.pair[0].set(0)
        self.pair[1].set(min(1, count - 1))
        rects = [(0, 0, max(1, width // 2), max(1, height // 2)), (width // 2, height // 2, width, height)]
        for variables, rect in zip(self.roi_vars, rects):
            for variable, value in zip(variables, rect):
                variable.set(value)
        self.curve_axis.clear()
        self.curve_axis.set_title("Color frame: spectral/state analysis disabled" if color else "ROI curves")
        if color:
            self.show_color()
        else:
            self.show_band()
        self.write_log(f"Opened {origin}; shape {'HWC' if color else 'HWK'}={cube.shape}, dtype={cube.data.dtype}, {cube.data.nbytes / 1024**2:.2f} MiB array. Source: {self.source.get()}")

    def color_channels(self):
        if self.cube is None:
            return None
        labels = self.cube.metadata.get("channel_labels")
        return labels if labels and len(labels) == self.cube.shape[2] else None

    def need_cube(self, *, allow_color=False):
        if self.cube is None:
            self.write_log("Open a local cube or generate the explicitly synthetic example first.")
            return False
        if self.color_channels() and not allow_color:
            self.write_log("This is a color-channel frame. Spectral/state analysis is disabled; use the color preview or channel slider.")
            return False
        return True

    def show_color(self):
        labels = self.color_channels()
        if not labels or len(labels) != 3 or set(labels) != {"R", "G", "B"}:
            self.write_log("Color preview requires explicit R/G/B channel labels.")
            return
        self.band_label.configure(text="Color preview; channels " + "/".join(labels))
        data = np.asarray(self.cube.data[:, :, [labels.index(label) for label in ("R", "G", "B")]])
        if data.dtype != np.uint8:
            maximum = (2 ** int(self.cube.metadata["effective_bits"]) - 1) if self.cube.metadata.get("effective_bits") else float(np.iinfo(data.dtype).max) if data.dtype.kind in "ui" else 1.0
            data = np.clip(data.astype(np.float32) / maximum, 0, 1)
        self.show_image(data, "RGB color preview / original color channels\nNot a spectral cube or colorimetric calibration")

    def show_image(self, data, title):
        self.image_axis.clear()
        self.image_axis.imshow(data, cmap="gray" if data.ndim == 2 else None)
        self.image_axis.set_title(title, fontsize=10)
        self.image_axis.set_xlabel("x pixel")
        self.image_axis.set_ylabel("y pixel")
        self.canvas.draw_idle()

    def show_band(self):
        if self.cube is None:
            return
        index = min(max(0, self.band.get()), self.cube.shape[2] - 1)
        wavelengths = self.cube.wavelengths
        color = self.color_channels()
        label = f"index {index}: {color[index]}" if color else f"index {index}" if wavelengths is None else f"index {index}; {wavelengths[index]:g} {self.cube.metadata.get('wavelength_units') or 'unit unknown'}"
        self.band_label.configure(text=label)
        plane = np.asarray(self.cube.data[:, :, index])
        valid = np.isfinite(plane)
        if self.cube.valid_mask is not None:
            valid &= self.cube.valid_mask if self.cube.valid_mask.ndim == 2 else self.cube.valid_mask[:, :, index]
        if self.cube.metadata.get("data_ignore_value") is not None:
            valid &= plane != self.cube.metadata["data_ignore_value"]
        if self.cube.metadata.get("band_validity") is not None:
            valid &= bool(self.cube.metadata["band_validity"][index])
        prefix = "Color channel " if color else "Raw sensor plane " if self.cube.metadata.get("data_level") == "raw_frame" else "Scan state " if wavelengths is None else "Band "
        self.show_image(np.ma.masked_where(~valid, plane), prefix + label)

    def show_composite(self):
        if self.color_channels():
            self.show_color()
        elif self.need_cube():
            bands = tuple(variable.get() for variable in self.channels)
            cube = self.cube
            self.worker("Computing composite…", lambda: composite(cube, bands), lambda result: self.show_image(result["image"], f"Composite indices {result['bands']} / wavelengths {result['wavelengths']}\nDisplay scaling; not colorimetric calibration"))

    def roi_rects(self):
        return [tuple(variable.get() for variable in variables) for variables in self.roi_vars]

    def show_rois(self):
        if self.need_cube():
            cube, rects = self.cube, self.roi_rects()
            self.worker("Computing two ROI mean / standard deviation curves…", lambda: [roi_statistics(cube, rect) for rect in rects], self.draw_rois)

    def draw_rois(self, results):
        self.roi_results = results
        self.show_band()
        self.curve_axis.clear()
        for number, (stats, color) in enumerate(zip(results, ("tab:orange", "tab:blue")), 1):
            x = stats["wavelengths"] if stats["wavelengths"] is not None else np.arange(len(stats["mean"]))
            mean, std = np.asarray(stats["mean"]), np.asarray(stats["std"])
            self.curve_axis.plot(x, mean, color=color, label=f"ROI {number}: mean ± SD")
            self.curve_axis.fill_between(x, mean - std, mean + std, color=color, alpha=0.2)
            x0, y0, x1, y1 = stats["rect"]
            self.image_axis.add_patch(Rectangle((x0 - 0.5, y0 - 0.5), x1 - x0, y1 - y0, fill=False, edgecolor=color, linewidth=2))
        self.curve_axis.legend(fontsize=8)
        self.curve_axis.set_xlabel(results[0]["axis_label"])
        self.curve_axis.set_ylabel(results[0]["units"])
        self.curve_axis.set_title("ROI valid pixels only")
        self.canvas.draw_idle()
        counts = [f"ROI {number}: {np.min(stats['count'])}–{np.max(stats['count'])} valid pixels/state" for number, stats in enumerate(results, 1)]
        self.write_log("; ".join(counts))

    def export_rois(self):
        if not self.need_cube():
            return
        cube, rects = self.cube, self.roi_rects()
        output = Path(self.output.get()) / ("roi_" + datetime.now().strftime("%Y%m%dT%H%M%S%f"))
        def export():
            output.mkdir(parents=True, exist_ok=False)
            results = [roi_statistics(cube, rect) for rect in rects]
            for number, stats in enumerate(results, 1):
                export_roi_csv(stats, output / f"roi_{number}.csv")
            return output
        self.worker("Exporting both ROI CSV files…", export, lambda path: self.write_log(f"Saved ROI CSV: {path}"))

    def show_pca(self):
        if self.need_cube():
            cube = self.cube
            def complete(result):
                scores = result["scores"]
                channels = []
                for index in range(scores.shape[2]):
                    plane = scores[:, :, index]
                    valid = plane[np.isfinite(plane)]
                    low, high = np.percentile(valid, (1, 99)) if valid.size else (0, 1)
                    channels.append(np.clip((plane - low) / max(float(high - low), 1e-12), 0, 1))
                while len(channels) < 3:
                    channels.append(np.zeros_like(channels[0]))
                self.show_image(np.stack(channels[:3], axis=2), "PCA display: sampled fit; centered, no band standardization")
                self.write_log(f"PCA explained variance ratio: {result['explained_variance_ratio']}; {result['metadata']}")
            self.worker("PCA: fitting at most 10,000 valid spectra and projecting in chunks…", lambda: pca(cube, n_components=min(3, cube.shape[2]), max_samples=10000), complete)

    def show_angle(self):
        if self.need_cube():
            cube, rect = self.cube, self.roi_rects()[0]
            def calculate():
                reference = roi_statistics(cube, rect)["mean"]
                return spectral_angle(cube, reference)
            self.worker("Computing angle difference from ROI 1 mean…", calculate, lambda result: self.show_image(result["data"], ("Spectral angle" if cube.wavelengths is not None else "State-vector angle difference") + " / radians; invalid zero vectors masked"))

    def show_pair(self, operation):
        if self.need_cube():
            cube, a, b = self.cube, self.pair[0].get(), self.pair[1].get()
            function = difference if operation == "difference" else ratio
            self.worker(f"Computing {operation}…", lambda: function(cube, a, b), lambda result: self.show_image(result["data"], f"{operation}: indices {a}, {b}; invalid values masked"))


def launch(path=None):
    root = tk.Tk()
    application = HyperLabApp(root)
    if path:
        application.load_path(path)
    root.mainloop()
