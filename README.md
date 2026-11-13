# GitHub Repository Trust Signals

> 💡 **Note for the team:** This is just a template. Update the above title with your AI Studio Challenge Project name. Remove all guidance notes and example text in this template and populate this README with your own content. You can work on this README throughout AI Studio, and get feedback from your AI Studio Coach and Challenge Advisor before finalizing it.  

---

### 👥 **Team Members**

**Example:**

| Name             | GitHub Handle | Contribution                                                             |
|------------------|---------------|--------------------------------------------------------------------------|
| Ethan Kemeny | [@e-kemeny](https://github.com/e-kemeny) | Led exploratory data analysis (EDA) and temporal analysis across 166 GitHub repositories, evaluated maintenance counterexamples, and documented findings with charts in [PR #11](https://github.com/Break-Through-Tech/Microsoft-3B-github-repo-trust-signals/pull/11). |
| Jordan Ramirez   | @jramirez     | Data collection, exploratory data analysis (EDA), dataset documentation  |
| Amina Hassan     | @aminahassan  | Data preprocessing, feature engineering, data validation                 |
| Priya Mehta      | @pmehta       | Model selection, hyperparameter tuning, model training and optimization  |
| Chris Park       | @chrispark    | Model evaluation, performance analysis, results interpretation           |

---

## 🎯 **Project Highlights**

**Example:**

- Developed a machine learning model using `[model type/technique]` to address `[challenge project task]`.
- Achieved `[key metric or result]`, demonstrating `[value or impact]` for `[host company]`.
- Generated actionable insights to inform business decisions at `[host company or stakeholders]`.
- Implemented `[specific methodology]` to address industry constraints or expectations.

---

## 👩🏽‍💻 **Setup and Installation**

<Please feel free to edit this as the project progresses>

Ensure that [uv](https://docs.astral.sh/uv/getting-started/installation/) is installed and available. Check with `uv --version`.

Create uv virtual environment and install dependencies:

```bash
uv sync --frozen --all-extras --all-groups
```

To update existing dependencies:

```bash
uv sync -U --all-extras --all-groups
```

### Code Quality

Format, lint, and type check (works for notebooks as well):

```bash
uv run ruff format && uv run ruff check --fix && uv run ty check
```

### Testing

Run tests:

```bash
uv run pytest
```

### GitHub API Token

This is optional but recommended. The [GitHub API client](src/gh_signals/github_client.py) can be provided authentication with your GitHub account for higher rate limits. There are a few options to do this:
- (Recommended) Install the [GH CLI](https://cli.github.com/) and run `gh auth token`
- Set a `GITHUB_TOKEN` environment variable
  - Go to [New fine-grained personal access token](https://github.com/settings/personal-access-tokens/new)
  - Name, description, expiration can be anything. Owner should be your account
  - Set Repository access to "Public repositories" and no permissions
  - Generate token
  - Copy and set it as an [environment variable](https://en.wikipedia.org/wiki/Environment_variable) on your system

**Important**: NEVER commit, include in a notebook, or share your token!

---

## 🏗️ **Project Overview**

This Microsoft-sponsored Break Through Tech AI Studio project investigates which signals help developers assess the trustworthiness of public GitHub repositories. We study repository activity, maintenance history, and other public GitHub data to identify signals that can support an assessment and give developers evidence they can inspect.

- How this project is connected to the Break Through Tech AI Program
- Your AI Studio host company and the project objective and scope
- The real-world significance of the problem and the potential impact of your work

---

## 📊 **Data Exploration**

For the preliminary activity analysis, we used a fixed snapshot of 166 public GitHub repositories: 112 known-good repositories and 54 comparison examples. The comparison group included 30 older repositories selected for maintenance concerns. We checked for duplicate repositories and missing metadata, then compared repository age and time since the last push across groups.

* The dataset(s) used: origin, format, size, type of data
* Data exploration and preprocessing approaches
* Insights from your Exploratory Data Analysis (EDA)
* Challenges and assumptions when working with the dataset(s)

**Potential visualizations to include:**

* Plots, charts, heatmaps, feature visualizations, sample dataset images

---

## 🧠 **Model Development**

We used logistic regression to test repository age and time since the last push as potential trust signals. We compared model performance across dataset versions to see how adding older repositories with maintenance concerns affected the results. This was a preliminary test of those two signals.

* Model(s) used (e.g., CNN with transfer learning, regression models)
* Feature selection and Hyperparameter tuning strategies
* Training setup (e.g., % of data for training/validation, evaluation metric, baseline performance)


---

## 📈 **Results & Key Findings**

In a snapshot of 166 GitHub repositories, repository age looked like a strong predictor until we added 30 older repositories selected for maintenance concerns. Recent push activity showed promise, but we selected some comparison repositories because development had slowed or stopped. We need to test that signal on repositories selected independently of their activity.

**You might consider describing the following (as applicable):**

* Performance metrics (e.g., Accuracy, F1 score, RMSE)
* How your model performed
* Insights from evaluating model fairness

**Potential visualizations to include:**

* Confusion matrix, precision-recall curve, feature importance plot, prediction distribution, outputs from fairness or explainability tools

---

## 🚀 **Next Steps**

- Validate time since the last push on a new set of repositories selected independently of their recent activity.
- Include well-maintained repositories with infrequent pushes to test whether the model can distinguish stable projects from abandoned ones.

* What are some of the limitations of your model?
* What would you do differently with more time/resources?
* What additional datasets or techniques would you explore?

---

## 📝 **License**

Specify how your project can be used by others. Choose an appropriate license and link it here (e.g., MIT, Apache 2.0). Make sure your Challenge Advisor approves of the selected license type. 

**Example:**
This project is licensed under the MIT License.

---

## 📄 **References** (Optional but encouraged)

Cite relevant papers, articles, or resources that supported your project.

---

## 🙏 **Acknowledgements** (Optional but encouraged)

Thank your Challenge Advisor, host company representatives, TA, and others who supported your project.
